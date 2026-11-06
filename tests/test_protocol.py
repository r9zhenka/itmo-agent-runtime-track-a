import json
import unittest
from pathlib import Path

from runtime.common import Fault, request_json
from runtime.contracts import CLIENT, SANDBOX, validate_request
from scripts.export_contracts import schemas
from tests.support import stack


class ProtocolTests(unittest.TestCase):
    def test_checked_in_schemas_match_runtime(self):
        root = Path(__file__).resolve().parents[1] / "contracts"
        for name, expected in schemas().items():
            self.assertEqual(json.loads((root / name).read_text()), expected)

    def test_invalid_requests(self):
        base = {"v": 0, "op": "exec", "session_id": "s", "operation_id": "o",
                "tool": "RunCommand", "arguments": {"command": "true"}, "timeout_s": 2}
        for updates in ({"v": 1}, {"v": False}, {"timeout_s": 0}, {"timeout_s": float("nan")},
                        {"timeout_s": 121}, {"session_id": "../escape"}, {"tool": "HostShell"}, {"extra": 1}):
            with self.subTest(updates=updates), self.assertRaises(Fault):
                validate_request({**base, **updates}, SANDBOX)
        self.assertEqual(validate_request(base, SANDBOX), "exec")
        with self.assertRaises(Fault):
            validate_request({"v": 0, "op": "create", "request_id": "a", "workspace": "x", "mode": "root"}, CLIENT)

    def test_auth_and_protocol_errors_over_http(self):
        with stack() as app:
            request = {"v": 0, "op": "collect", "session_id": "missing"}
            with self.assertRaises(Fault) as raised:
                request_json(app["url"] + "/v0", request, "wrong-token")
            self.assertEqual(raised.exception.status, 401)
            with self.assertRaises(Fault) as raised:
                request_json(app["url"] + "/v0", {"v": 7}, "client-token")
            self.assertEqual(raised.exception.kind, "validation")
            with self.assertRaises(Fault) as raised:
                list(app["client"].event_batch("missing"))
            self.assertEqual(raised.exception.status, 404)
