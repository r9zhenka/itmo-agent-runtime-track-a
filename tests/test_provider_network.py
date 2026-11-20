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


class ProviderFailureTests(unittest.TestCase):
    def dispatch(self, reply):
        proxy = ModelProxy('live', 'https://provider.example/v1', 'SECRET-CANARY', 'model')
        with patch('runtime.llm_proxy.request_json', return_value=reply):
            return proxy.dispatch({'op': 'complete', 'messages': [], 'tools': []})

    def test_finish_reason_keeps_known_usage_without_body(self):
        for reason, expected in (('length', 'length'), ('content_filter', 'content_filter'),
                                 ('SECRET-CANARY', 'other')):
            reply = {'choices': [{'finish_reason': reason, 'message': {'role': 'assistant', 'content': 'SECRET-CANARY'}}],
                     'usage': {'total_tokens': 57, 'prompt_tokens': 50, 'completion_tokens': 7, 'private': 'SECRET-CANARY'}}
            with self.assertRaises(Fault) as caught:
                self.dispatch(reply)
            details = caught.exception.as_dict()['error']['details']
            self.assertEqual(details['category'], 'finish_reason')
            self.assertEqual(details['finish_reason'], expected)
            self.assertEqual(details['usage']['total_tokens'], 57)
            self.assertTrue(details['usage_complete'])
            self.assertNotIn('SECRET-CANARY', json.dumps(caught.exception.as_dict()))

    def test_malformed_response_usage_is_sanitized_and_retained(self):
        with self.assertRaises(Fault) as caught:
            self.dispatch({'choices': [], 'usage': {'total_tokens': 9, 'prompt_tokens': True,
                                                   'completion_tokens': -1, 'private': 'SECRET-CANARY'}})
        details = caught.exception.as_dict()['error']['details']
        self.assertEqual(details['category'], 'invalid_response')
        self.assertEqual(details['usage'], {'total_tokens': 9})

    def test_transport_failures_expose_safe_category_only(self):
        import io
        import urllib.error
        from runtime.provider_transport import request_json as provider_request
        failures = [(TimeoutError('SECRET-CANARY'), 'timeout', None),
                    (urllib.error.URLError(TimeoutError('SECRET-CANARY')), 'timeout', None),
                    (urllib.error.URLError('SECRET-CANARY'), 'transport', None),
                    (urllib.error.HTTPError('https://secret.example', 429, 'SECRET-CANARY', {},
                                           io.BytesIO(b'SECRET-CANARY')), 'http', 429)]
        for failure, category, status in failures:
            with self.subTest(category=category):
                with patch('runtime.provider_transport.urllib.request.build_opener') as opener:
                    opener.return_value.open.side_effect = failure
                    with self.assertRaises(Fault) as caught:
                        provider_request('https://provider.example/v1', {}, 'SECRET-CANARY')
                public = caught.exception.as_dict()
                self.assertNotIn('SECRET-CANARY', json.dumps(public))
                self.assertNotIn('secret.example', json.dumps(public))
                details = public['error']['details']
                self.assertEqual(details['category'], category)
                self.assertFalse(details['usage_complete'])
                if status is not None:
                    self.assertEqual(details['http_status'], status)

    def test_invalid_json_and_oversized_body_fail_without_echo(self):
        from runtime.common import MAX_BODY
        from runtime.provider_transport import request_json as provider_request
        for raw in (b'SECRET-CANARY invalid json', b'x' * (MAX_BODY + 1), b'[]'):
            with patch('runtime.provider_transport.urllib.request.build_opener') as opener:
                opener.return_value.open.return_value.__enter__.return_value.read.return_value = raw
                with self.assertRaises(Fault) as caught:
                    provider_request('https://provider.example/v1', {}, 'SECRET-CANARY')
            self.assertEqual(caught.exception.details['category'], 'invalid_response')
            self.assertNotIn('SECRET-CANARY', json.dumps(caught.exception.as_dict()))
