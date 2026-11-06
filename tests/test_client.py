import contextlib
import io
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import Mock

from baf.cases import cases, prepare, prompt
from client.__main__ import main
from client.api import Client, edit
from runtime.common import Fault
from tests.support import stack


class ClientTests(unittest.TestCase):
    def test_invalid_workspace_is_rejected_before_network_access(self):
        client = Client("http://127.0.0.1:1", "token")
        client.check_server = Mock()
        client.rpc = Mock()
        for workspace in ("", "   ", ".", "../outside", "/absolute/path"):
            with self.subTest(workspace=workspace), self.assertRaises(Fault) as raised:
                client.create(workspace)
            self.assertIn("folder", str(raised.exception))
        client.check_server.assert_not_called()
        client.rpc.assert_not_called()

    def test_connect_rejects_wrong_service_without_sending_credentials(self):
        for status, response in ((404, {"detail": "Not Found"}),
                                 (200, {"v": 0, "status": "ok", "service": "harness"})):
            requests = []

            class ForeignHandler(BaseHTTPRequestHandler):
                def log_message(self, *_):
                    pass

                def do_GET(self):
                    requests.append((self.command, self.path, self.headers.get("Authorization")))
                    raw = json.dumps(response).encode()
                    self.send_response(status)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)

                def do_POST(self):
                    requests.append((self.command, self.path, self.headers.get("Authorization")))
                    self.send_error(500)

            http = ThreadingHTTPServer(("127.0.0.1", 0), ForeignHandler)
            thread = threading.Thread(target=http.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
            thread.start()
            try:
                client = Client(f"http://127.0.0.1:{http.server_port}", "PRIVATE-TOKEN")
                with self.subTest(status=status), self.assertRaises(Fault) as raised:
                    client.create("demo")
                self.assertIn("Project A gateway", str(raised.exception))
                if status == 404:
                    self.assertEqual(raised.exception.status, 404)
                    self.assertIn("HTTP 404", str(raised.exception))
                self.assertEqual(requests, [("GET", "/health", None)])
            finally:
                http.shutdown()
                http.server_close()
                thread.join(timeout=2)

    def test_cli_connect_send_stream_collect_cancel_release(self):
        with stack() as app:
            case = cases()[0]
            prepare(case, app["root"] / "demo")
            base = ["--server", app["url"], "--token", "client-token"]

            def invoke(*args):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    self.assertEqual(main([*base, *args]), 0)
                return [json.loads(line) for line in output.getvalue().splitlines()]

            sid = invoke("connect", "--workspace", "demo", "--request-id", "connect")[0]["session_id"]
            self.assertEqual(sid, invoke("connect", "--workspace", "demo", "--request-id", "connect")[0]["session_id"])
            events = invoke("send", "--session", sid, "--text", prompt(case), "--wait")
            self.assertEqual(events[-1]["type"], "result")
            self.assertEqual(events[-1]["outcome"], "success")
            self.assertEqual((app["root"] / "demo/answer.txt").read_text().strip(), "8137")
            invoke("edit", "--folder", str(app["root"] / "demo"), "--file", "answer.txt", "--append", "READY")
            self.assertIn("READY", (app["root"] / "demo/answer.txt").read_text())
            self.assertEqual(len(invoke("collect", "--session", sid)[0]["results"]), 1)
            invoke("cancel", "--session", sid)
            invoke("release", "--session", sid)

    def test_reconnect_resumes_without_duplicate_events(self):
        with stack() as app:
            case = cases()[0]
            prepare(case, app["root"] / "demo")
            client = app["client"]
            sid = client.create("demo")
            run = client.send(sid, prompt(case))
            all_events = list(client.watch(sid, run))
            cursor = all_events[1]["seq"]
            resumed = list(client.watch(sid, run, after=cursor))
            self.assertEqual(resumed, all_events[2:])
            self.assertEqual(len([e for e in resumed if e["type"] == "result"]), 1)
            client.release(sid)

    def test_edit_rejects_outside_folder(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(Fault):
            edit(tmp, "../outside", "data")
