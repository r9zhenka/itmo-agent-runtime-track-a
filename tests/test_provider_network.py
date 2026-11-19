import json
import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from runtime.common import Fault, request_json
from runtime.llm_proxy import ModelProxy


class ProviderNetworkTests(unittest.TestCase):
    def server(self, handler):
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
        thread.start()

        def close():
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
        self.addCleanup(close)
        return f"http://127.0.0.1:{server.server_port}"

    def test_redirect_never_forwards_bearer_credentials_to_another_endpoint(self):
        received = []

        class Sink(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                received.append(self.headers.get("Authorization"))
                body = b'{"ok":true}'
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            do_POST = do_GET
        target = self.server(Sink)

        class Redirect(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                self.rfile.read(int(self.headers.get("Content-Length", "0")))
                self.send_response(302)
                self.send_header("Location", target + "/stolen")
                self.send_header("Content-Length", "0")
                self.end_headers()
        origin = self.server(Redirect)
        with self.assertRaises(Fault) as caught:
            request_json(origin, {"message": "hello"}, "SECRET-CANARY", timeout=2)
        self.assertNotIn("SECRET-CANARY", json.dumps(caught.exception.as_dict()))
        self.assertEqual(received, [])

    def test_internal_requests_ignore_workstation_proxy_environment(self):
        received = []

        class Endpoint(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                received.append(self.path)
                body = b'{"direct":true}'
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        endpoint = self.server(Endpoint)
        # A broken inherited proxy must not redirect or break internal RPC.
        with patch.dict(os.environ, {"http_proxy": "http://127.0.0.1:1", "HTTP_PROXY": "http://127.0.0.1:1",
                                     "no_proxy": "", "NO_PROXY": "", "all_proxy": "http://127.0.0.1:1"}):
            self.assertEqual(request_json(endpoint + "/health", timeout=2), {"direct": True})
        self.assertEqual(received, ["/health"])

    def test_model_output_budget_is_explicit_and_bounded(self):
        for value in (0, -1, 4097, True, 2048.0, "2048"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                ModelProxy(extra={"max_tokens": value})
        with self.assertRaises(ValueError):
            ModelProxy(extra={"max_completion_tokens": 4096})
        proxy = ModelProxy("live", "https://provider.example/v1", "KEY", "model")
        reply = {"choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": "ok"}}]}
        with patch("runtime.llm_proxy.request_json", return_value=reply) as request:
            proxy.dispatch({"op": "complete", "messages": [], "tools": []})
        self.assertEqual(request.call_args.args[1]["max_tokens"], 2048)
