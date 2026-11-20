import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from client.api import Client
from runtime.common import Fault, request_json
from runtime.gateway import Gateway
from runtime.harness import Harness
from tests.support import server


class LifecycleTests(unittest.TestCase):
    def test_cancel_between_steps_waits_for_cleanup_and_reports_failure(self):
        for fail in (False, True):
            with self.subTest(cleanup_fails=fail), tempfile.TemporaryDirectory() as tmp:
                between, resume = threading.Event(), threading.Event()
                cleaning, finish_cleanup = threading.Event(), threading.Event()
                errors = []

                def steps(_):
                    yield 0
                    between.set()
                    if not resume.wait(3):
                        raise RuntimeError('test synchronization timeout')
                    yield 1

                def sandbox(op, **args):
                    if op == 'cancel':
                        cleaning.set()
                        if not finish_cleanup.wait(3):
                            raise RuntimeError('test synchronization timeout')
                        if fail:
                            raise Fault('sandbox', 'test cleanup failed', 503)
                    return {'v': 0, 'error': None, 'stdout': '', 'stderr': '', 'exit_code': 0}

                def model(*args, **kwargs):
                    return {'message': {'role': 'assistant', 'content': None, 'tool_calls': [
                        {'id': 'call', 'function': {'name': 'ReadFile', 'arguments': '{"path":"test"}'}}]},
                        'usage': {'total_tokens': 2}}

                harness = Harness(sandbox, model, tmp)
                sid = harness.create('request', 'folder', 'rw')['session_id']
                with patch('runtime.harness.range', steps, create=True):
                    harness.message(sid, 'message', 'test')
                    self.assertTrue(between.wait(3))
                    def cancel():
                        try:
                            harness.cancel(sid)
                        except Fault as exc:
                            errors.append(exc.kind)
                    thread = threading.Thread(target=cancel)
                    thread.start()
                    self.assertTrue(cleaning.wait(3))
                    resume.set()
                    harness.session(sid)['current']['thread'].join(3)
                    self.assertEqual(harness.collect(sid)['results'], [])
                    finish_cleanup.set()
                    thread.join(3)
                results = harness.collect(sid)['results']
                self.assertEqual(len(results), 1)
                self.assertEqual(results[0]['outcome'], 'error' if fail else 'cancelled')
                self.assertEqual(errors, ['sandbox'] if fail else [])

    def test_released_sessions_do_not_exhaust_active_capacity(self):
        with tempfile.TemporaryDirectory() as tmp:
            harness = Harness(lambda *a, **kw: {}, None, tmp, session_limit=2, retained_sessions=3)
            for i in range(140):
                sid = harness.create(str(i), 'folder', 'rw')['session_id']
                harness.release(sid)
            self.assertLessEqual(len(harness.sessions), 4)
            self.assertLessEqual(len(harness.requests), 4)
            one = harness.create('one', 'one', 'rw')['session_id']
            harness.create('two', 'two', 'rw')
            with self.assertRaises(Fault) as caught:
                harness.create('three', 'three', 'rw')
            self.assertEqual(caught.exception.status, 429)
            self.assertEqual(harness.create('one', 'one', 'rw')['session_id'], one)
            with self.assertRaises(Fault):
                harness.create('one', 'changed', 'rw')

    def test_provider_failure_preserves_safe_details_and_known_usage(self):
        details = {'category': 'finish_reason', 'finish_reason': 'length',
                   'usage': {'total_tokens': 42}, 'usage_complete': True}
        def model(*a, **kw):
            raise Fault('model', 'Incomplete completion', 502, details=details)
        with tempfile.TemporaryDirectory() as tmp:
            harness = Harness(lambda *a, **kw: {}, model, tmp)
            sid = harness.create('c', 'w', 'rw')['session_id']
            harness.message(sid, 'm', 'test')
            harness.session(sid)['current']['thread'].join(3)
            result = harness.collect(sid)['results'][0]
            self.assertEqual(result['tokens'], 42)
            self.assertEqual(result['error']['details'], details)


    def test_trace_disk_failure_does_not_strand_run_or_duplicate_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            harness = Harness(lambda *a, **kw: {}, lambda *a, **kw: {
                "message": {"role": "assistant", "content": "done"}}, tmp)
            sid = harness.create("c", "w", "rw")["session_id"]
            with patch("runtime.harness.Path.open", side_effect=OSError("test disk failure")):
                accepted = harness.message(sid, "m", "test")
                harness.session(sid)["current"]["thread"].join(3)
                self.assertEqual(accepted, harness.message(sid, "m", "test"))
            results = harness.collect(sid)["results"]
            self.assertEqual(len(results), 1)
            self.assertFalse(results[0]["trace_persisted"])
            self.assertEqual(results[0]["outcome"], "success")

    def test_worker_launch_failure_produces_one_replayable_terminal(self):
        with tempfile.TemporaryDirectory() as tmp:
            harness = Harness(lambda *a, **kw: {}, None, tmp)
            sid = harness.create("c", "w", "rw")["session_id"]
            with patch("runtime.harness.threading.Thread.start", side_effect=RuntimeError("no threads")):
                accepted = harness.message(sid, "m", "test")
            self.assertEqual(accepted, harness.message(sid, "m", "test"))
            results = harness.collect(sid)["results"]
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["outcome"], "error")


class IdentityTests(unittest.TestCase):
    def test_identity_cannot_read_or_mutate_another_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            harness = Harness(lambda *a, **kw: {}, None, tmp)
            gateway = Gateway(lambda op, **args: harness.dispatch({'v': 0, 'op': op, **args}))
            with server(gateway, {'alice': 'alice-secret', 'bob': 'bob-secret'}) as url:
                alice, bob = Client(url, 'alice-secret'), Client(url, 'bob-secret')
                a = alice.create('folder-a', request_id='same-request')
                b = bob.create('folder-b', request_id='same-request')
                self.assertNotEqual(a, b)
                self.assertEqual(alice.create('folder-a', request_id='same-request'), a)
                for op in ('collect', 'cancel', 'release', 'message'):
                    body = {'v': 0, 'op': op, 'session_id': a}
                    if op == 'message': body.update(request_id='m', text='test')
                    with self.subTest(op=op), self.assertRaises(Fault) as caught:
                        request_json(url + '/v0', body, 'bob-secret')
                    self.assertEqual(caught.exception.status, 403)
                with self.assertRaises(Fault) as caught:
                    list(bob.event_batch(a))
                self.assertEqual(caught.exception.status, 403)
                with self.assertRaises(Fault) as caught:
                    Client(url, 'wrong').collect(a)
                self.assertEqual(caught.exception.status, 401)
                self.assertFalse(harness.session(a)['cancelled'])
                alice.release(a)
                bob.release(b)

    def test_real_interrupted_event_response_resumes_and_deduplicates(self):
        from urllib.parse import parse_qs, urlsplit
        cursors = []
        first = {"v": 0, "seq": 1, "session_id": "s", "trace_id": "r", "run_id": "r", "type": "started"}
        final = {"v": 0, "seq": 2, "session_id": "s", "trace_id": "r", "run_id": "r", "type": "result",
                 "outcome": "success", "duration_ms": 1, "tokens": 0}
        class Interrupted(BaseHTTPRequestHandler):
            def log_message(self, *a): pass
            def do_GET(self):
                cursors.append(int(parse_qs(urlsplit(self.path).query)["after"][0]))
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(("data: " + json.dumps(first) + "\n\n").encode())
                if len(cursors) == 1:
                    self.wfile.write(b'data: {"seq":2')  # A connection lost halfway through an event.
                else:
                    self.wfile.write(("data: " + json.dumps(final) + "\n\n").encode())
                self.wfile.flush()
                self.close_connection = True
        http = ThreadingHTTPServer(("127.0.0.1", 0), Interrupted)
        threading.Thread(target=http.serve_forever, daemon=True).start()
        try:
            result = list(Client(f"http://127.0.0.1:{http.server_port}", "dummy").watch("s", "r", timeout=3))
            self.assertEqual(result, [first, final])
            self.assertEqual(cursors, [0, 1])
        finally:
            http.shutdown(); http.server_close()

    def test_event_redirect_does_not_forward_authorization(self):
        seen = []
        class Sink(BaseHTTPRequestHandler):
            def log_message(self, *a): pass
            def do_GET(self):
                seen.append(self.headers.get('Authorization'))
                self.send_response(200); self.send_header('Content-Length', '0'); self.end_headers()
        sink = ThreadingHTTPServer(('127.0.0.1', 0), Sink)
        class Redirect(BaseHTTPRequestHandler):
            def log_message(self, *a): pass
            def do_GET(self):
                self.send_response(302)
                self.send_header('Location', f'http://127.0.0.1:{sink.server_port}/capture')
                self.send_header('Content-Length', '0'); self.end_headers()
        source = ThreadingHTTPServer(('127.0.0.1', 0), Redirect)
        for http in (source, sink): threading.Thread(target=http.serve_forever, daemon=True).start()
        try:
            with self.assertRaises(Fault) as caught:
                list(Client(f'http://127.0.0.1:{source.server_port}', 'dummy-secret').event_batch('s'))
            self.assertEqual(caught.exception.status, 302)
            self.assertEqual(seen, [])
        finally:
            for http in (source, sink): http.shutdown(); http.server_close()
