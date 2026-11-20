"""Provider-only HTTPS transport with bounded, credential-free failure metadata."""
import json
import http.client
import socket
import urllib.error
import urllib.request

from .common import Fault, MAX_BODY, RejectRedirects, UnixProxyHTTPSHandler


def safe_usage(value):
    if not isinstance(value, dict):
        return {}
    return {key: value[key] for key in ("prompt_tokens", "completion_tokens", "total_tokens")
            if type(value.get(key)) is int and 0 <= value[key] <= 1_000_000_000}


def provider_fault(category, *, http_status=None, finish_reason=None, usage=None):
    messages = {"http": "Provider returned an HTTP error", "timeout": "Provider request timed out",
                "transport": "Provider connection failed", "invalid_response": "Provider returned an invalid response",
                "finish_reason": "Provider completion did not finish normally"}
    usage = safe_usage(usage)
    details = {"category": category, "usage": usage, "usage_complete": "total_tokens" in usage}
    if http_status is not None:
        details["http_status"] = http_status
    if finish_reason is not None:
        details["finish_reason"] = finish_reason if finish_reason in ("length", "content_filter", "function_call", "stop", "tool_calls") else "other"
    return Fault("model", messages[category], 502,
                 category in ("timeout", "transport") or category == "http" and (http_status == 429 or http_status >= 500),
                 details=details)


def request_json(url, body, token, timeout=90, proxy_url="", proxy_socket=""):
    """Never propagate provider error bodies, response headers, URLs or exceptions."""
    if not url.startswith("https://") or proxy_url and proxy_socket:
        raise ValueError("Provider transport requires HTTPS and one proxy route")
    request = urllib.request.Request(url, data=json.dumps(body).encode(), headers={
        "Content-Type": "application/json", "Authorization": "Bearer " + token})
    handlers = [urllib.request.ProxyHandler({"https": proxy_url or "http://localhost"}
                                           if proxy_url or proxy_socket else {}), RejectRedirects()]
    if proxy_socket:
        handlers.append(UnixProxyHTTPSHandler(proxy_socket))
    try:
        with urllib.request.build_opener(*handlers).open(request, timeout=timeout) as response:
            raw = response.read(MAX_BODY + 1)
        if len(raw) > MAX_BODY:
            raise provider_fault("invalid_response")
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise provider_fault("invalid_response")
        return parsed
    except urllib.error.HTTPError as exc:
        status = exc.code
        exc.close()
        raise provider_fault("http", http_status=status) from None
    except (TimeoutError, socket.timeout):
        raise provider_fault("timeout") from None
    except urllib.error.URLError as exc:
        category = "timeout" if isinstance(exc.reason, (TimeoutError, socket.timeout)) else "transport"
        raise provider_fault(category) from None
    except (UnicodeError, ValueError):
        raise provider_fault("invalid_response") from None
    except (OSError, http.client.HTTPException):
        raise provider_fault("transport") from None
