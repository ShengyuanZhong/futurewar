import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from app.config import Settings
from app.server import AgentServer
from app.service.turn_service import TurnService, empty_response
from tests.fixtures import request


class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = AgentServer(("127.0.0.1", 0), TurnService(Settings(enable_news=False)))
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def call(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection(*self.server.server_address, timeout=3)
        try:
            conn.request(method, path, body=body, headers=headers or {})
            response = conn.getresponse()
            data = response.read()
            self.assertEqual(int(response.getheader("Content-Length")), len(data))
            return response.status, json.loads(data)
        finally:
            conn.close()

    def test_health(self):
        self.assertEqual(self.call("GET", "/health")[0], 200)
        self.assertEqual(self.call("GET", "/missing")[0], 404)

    def test_valid_post_any_path_full_response(self):
        raw = request()
        raw["teamOur"]["teamId"] = "http-smoke"
        body = json.dumps(raw, ensure_ascii=False).encode()
        status, result = self.call("POST", "/judger", body, {"Content-Type": "application/json"})
        self.assertEqual(status, 200)
        self.assertEqual(set(result), {"roleCommandMap", "prompt", "executeCmd"})
        self.assertEqual(result["roleCommandMap"]["502"], {"action": "acceptTask"})
        for worker in ("501", "504"):
            self.assertIn(result["roleCommandMap"][worker]["action"], ("move", "build"))
        self.assertFalse(any(c["action"] == "collect" for c in result["roleCommandMap"].values()))
        self.assertEqual(self.call("POST", "/", body)[1], result)

    def test_malformed_body_is_not_silent_success(self):
        for body in (b"{bad", b"[]", b"null", b'{}', b'{"roundNo":NaN}'):
            with self.subTest(body=body):
                status, response = self.call("POST", "/", body)
                self.assertEqual(status, 400)
                self.assertEqual(response, empty_response())

    def test_oversized_body_is_rejected_before_reading(self):
        status, _ = self.call("POST", "/", b"", {"Content-Length": "2097153"})
        self.assertEqual(status, 413)

    def test_internal_failure_returns_safe_body_and_logs(self):
        raw = request()
        with patch.object(self.server.service, "decide", side_effect=RuntimeError("fixture")), self.assertLogs("app.server", level="ERROR") as logs:
            status, result = self.call("POST", "/", json.dumps(raw).encode())
        self.assertEqual((status, result), (200, empty_response()))
        self.assertIn("decision_failed", logs.output[0])


class ConfigTests(unittest.TestCase):
    def load(self, raw):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "config.json"
            path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
            return Settings.load(str(path))

    def test_example_enables_base_surroundings(self):
        settings = Settings.load(str(Path(__file__).resolve().parents[1] / "config.example.json"))
        self.assertTrue(settings.allow_base_surroundings)
        self.assertEqual(settings.layouts, {})
        self.assertEqual(settings, Settings())

    def test_invalid_config_fails_at_startup(self):
        for raw in ({"surprise": 1}, {"loadout": ["laser", "rocket", "gatling"]}, {"sell_batch": 0},
                    {"repair_stock": 0}, {"repair_stock": 101}, {"repair_start_day": 11},
                    {"repair_threshold_percent": 101}, {"repair_threshold_percent": True},
                    {"enable_news": "true"}, {"allow_base_surroundings": "true"},
                    {"layouts": {"challenger": {"verified": True, "source": "", "weapons": [], "walls": []}}}):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                self.load(raw)

    def test_overlap_is_rejected(self):
        with self.assertRaises(ValueError):
            self.load({"layouts": {"challenger": {"verified": True, "source": "test",
                "weapons": [{"x": -1, "y": 0}], "walls": [{"x": -1, "y": 0}]}}})
