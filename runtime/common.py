import hmac
import http.client
import json
import os
import socket
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

MAX_BODY = 1_048_576


class Fault(Exception):
    def __init__(self, kind, message, status=400, retryable=False, details=None):
        super().__init__(message)
        self.kind, self.message, self.status = kind, message, status
        self.retryable = retryable
        self.details = details

    def as_dict(self):
        return {"v": 0, "error": {"kind": self.kind, "message": self.message,
                                  "retryable": self.retryable,
                                  **({"details": self.details} if self.details is not None else {})}}


class UnixProxyHTTPSHandler(urllib.request.HTTPSHandler):
    """HTTP CONNECT through an SSH-forwarded Unix socket; TLS remains end-to-end."""
    def __init__(self, path):
        super().__init__()
        self.path = path

    def https_open(self, req):
        path = self.path
        class Connection(http.client.HTTPSConnection):
            def connect(self):
                if not self._tunnel_host:
                    raise ValueError("Unix provider proxy requires HTTPS CONNECT")
                sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                try:
                    sock.settimeout(self.timeout)
                    sock.connect(path)
                    self.sock = sock
                    self._tunnel()
                    self.sock = self._context.wrap_socket(sock, server_hostname=self._tunnel_host)
                except BaseException:
                    sock.close()
                    raise
        return self.do_open(Connection, req, context=self._context)


class RejectRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Fixed RPC endpoints must never forward bearer credentials to a new URL.
        return None


def request_json(url, body=None, token="", timeout=40, proxy_url="", proxy_socket=""):
    data = None if body is None else json.dumps(body).encode()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url, data=data, headers=headers)
    # Explicit opt-in for the provider only. Internal calls never inherit proxies.
    if proxy_url and proxy_socket:
        raise ValueError("Choose one provider proxy transport")
    proxies = {"https": proxy_url or "http://localhost"} if proxy_url or proxy_socket else {}
    handlers = [urllib.request.ProxyHandler(proxies), RejectRedirects()]
    if proxy_socket:
        handlers.append(UnixProxyHTTPSHandler(proxy_socket))
    opener = urllib.request.build_opener(*handlers)
    try:
        with opener.open(req, timeout=timeout) as response:
            raw = response.read(MAX_BODY + 1)
            if len(raw) > MAX_BODY:
                raise Fault("transport", "Response exceeds size limit", 502)
            return json.loads(raw)
    except urllib.error.HTTPError as exc:
        try:
            err = json.loads(exc.read(MAX_BODY))["error"]
            if not isinstance(err, dict) or not isinstance(err.get("kind"), str) or not isinstance(err.get("message"), str):
                raise ValueError("Unexpected error format")
            raise Fault(err["kind"], err["message"], exc.code, err.get("retryable", False), err.get("details"))
        except (ValueError, KeyError, TypeError):
            raise Fault("transport", f"HTTP {exc.code}: server returned an unexpected error format; check the server address and port",
                        exc.code, exc.code >= 500) from None
        finally:
            exc.close()
    except (OSError, ValueError, urllib.error.URLError):
        raise Fault("transport", "Upstream unavailable or invalid response", 502, True) from None


class Remote:
    def __init__(self, url, token, timeout=40):
        self.url, self.token, self.timeout = url.rstrip("/"), token, timeout

    def __call__(self, op, **args):
        return request_json(self.url + "/v0", {"v": 0, "op": op, **args},
                            self.token, self.timeout)


    def execute(self, *, on_event=None, **args):
        """Consume the manager's resumable operation event stream; never retry start.

        A failed start response can hide execution, so callers retain their operation
        ID for explicit reconciliation. Read-only event fetches can be repeated.
        """
        import time
        accepted = self("start", **args)
        cursor = accepted["after"]
        deadline = time.monotonic() + args["timeout_s"] + 40
        while time.monotonic() < deadline:
            for event in self("events", session_id=args["session_id"], after=cursor)["events"]:
                if event["seq"] <= cursor:
                    continue
                cursor = event["seq"]
                if event["operation_id"] != args["operation_id"]:
                    continue
                if on_event:
                    on_event(event)
                if event["type"] == "result":
                    return event["result"]
        raise Fault("transport", "Sandbox event stream did not produce a terminal result; reconcile the operation ID", 504)


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def make_server(app, token, host="0.0.0.0", port=8000):
    identities = token if isinstance(token, dict) else {"default": token}
    if (not identities or any(not isinstance(name, str) or not name or
            not isinstance(secret, str) or not secret for name, secret in identities.items())
            or len(set(identities.values())) != len(identities)):
        raise ValueError("Authentication requires distinct nonempty tokens and identity names")

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def setup(self):
            super().setup()
            self.connection.settimeout(45)

        def log_message(self, *_):
            pass  # Do not log tokens, query strings, or user content.

        def send_json(self, value, status=200):
            raw = json.dumps(value).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def authenticate(self):
            supplied = self.headers.get("Authorization", "").encode("utf-8")
            principal = None
            for name, secret in identities.items():
                if hmac.compare_digest(supplied, ("Bearer " + secret).encode("utf-8")):
                    principal = name
            if principal is None:
                raise Fault("auth", "Invalid bearer token", 401)
            return principal

        def do_GET(self):
            try:
                path = urlsplit(self.path)
                if path.path == "/health":
                    self.send_json(app.health())
                    return
                principal = self.authenticate()
                if path.path != "/v0/events" or not hasattr(app, "events"):
                    raise Fault("validation", "Unknown endpoint", 404)
                query = parse_qs(path.query)
                sid = query.get("session_id", [""])[0]
                try:
                    after = int(query.get("after", ["0"])[0])
                    if after < 0:
                        raise ValueError()
                except ValueError:
                    raise Fault("validation", "Invalid event cursor") from None
                # A finite SSE response; reconnect with the last event ID.
                events = (app.events_authenticated(sid, after, principal)
                          if hasattr(app, "events_authenticated") else app.events(sid, after))
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "close")
                self.end_headers()
                self.close_connection = True
                for event in events:
                    self.wfile.write((f"id: {event['seq']}\nevent: {event['type']}\n"
                                      f"data: {json.dumps(event)}\n\n").encode())
                    self.wfile.flush()
                self.wfile.write(b": reconnect\n\n")
            except Fault as exc:
                self.send_json(exc.as_dict(), exc.status)
            except (BrokenPipeError, ConnectionResetError, socket.timeout):
                pass

        def do_POST(self):
            try:
                principal = self.authenticate()
                if self.path != "/v0":
                    raise Fault("validation", "Unknown endpoint", 404)
                try:
                    size = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    raise Fault("validation", "Invalid Content-Length") from None
                if not 0 < size <= MAX_BODY:
                    raise Fault("validation", "Invalid request size", 413)
                try:
                    body = json.loads(self.rfile.read(size))
                except (ValueError, UnicodeDecodeError):
                    raise Fault("validation", "Invalid JSON") from None
                if not isinstance(body, dict) or type(body.get("v")) is not int or body["v"] != 0:
                    raise Fault("validation", "Expected protocol v=0")
                self.send_json(app.dispatch_authenticated(body, principal)
                               if hasattr(app, "dispatch_authenticated") else app.dispatch(body))
            except Fault as exc:
                self.close_connection = True
                self.send_json(exc.as_dict(), exc.status)
            except (BrokenPipeError, ConnectionResetError, socket.timeout):
                pass
            except Exception:
                self.close_connection = True
                self.send_json(Fault("sandbox", "Internal service error", 500).as_dict(), 500)

    return Server((host, port), Handler)


def serve(app, token):
    import signal
    server = make_server(app, token, port=int(os.getenv("PORT", "8000")))

    def stop(*_):
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        if hasattr(app, "close"):
            app.close()
