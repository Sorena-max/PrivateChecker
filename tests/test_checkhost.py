import unittest
from unittest import mock

from privatechecker import checkhost

NODES = {"nodes": {
    "de1.node.check-host.net": {"location": ["de", "Germany", "Nuremberg"]},
    "ir1.node.check-host.net": {"location": ["ir", "Iran", "Tehran"]},
    "ir3.node.check-host.net": {"location": ["ir", "Iran", "Mashhad"]},
}}


class ParseTests(unittest.TestCase):
    def test_nodes_filtered_to_iran(self):
        found = checkhost.parse_nodes(NODES)
        self.assertEqual(found, [("ir1.node.check-host.net", "Tehran"),
                                 ("ir3.node.check-host.net", "Mashhad")])

    def test_ping_ok_and_partial(self):
        value = [[["OK", 0.05, "1.1.1.1"], ["OK", 0.07, "1.1.1.1"],
                  ["TIMEOUT", 3.0], ["MALFORMED", 0.0]]]
        res = checkhost.parse_ping(value)
        self.assertEqual((res["ok"], res["total"]), (2, 4))
        self.assertAlmostEqual(res["avg_ms"], 60.0)

    def test_ping_pending_and_error(self):
        self.assertIsNone(checkhost.parse_ping(None))
        self.assertIsNone(checkhost.parse_ping([None]))
        self.assertEqual(checkhost.parse_ping([{"error": "x"}])["ok"], 0)

    def test_tcp(self):
        ok = checkhost.parse_tcp([{"time": 0.0123, "address": "1.1.1.1"}])
        self.assertTrue(ok["ok"])
        self.assertAlmostEqual(ok["ms"], 12.3)
        bad = checkhost.parse_tcp([{"error": "Connection timed out"}])
        self.assertFalse(bad["ok"])
        self.assertIsNone(checkhost.parse_tcp([None]))

    def test_summarize_ignores_pending_nodes(self):
        report = {"nodes": [{"ping": {"ok": 4, "total": 4}},
                            {"ping": {"ok": 0, "total": 4}},
                            {"ping": None}]}
        self.assertEqual(checkhost.summarize(report), (1, 2))


class FlowTests(unittest.TestCase):
    def fake_get(self, path, timeout=15):
        if path.startswith("/nodes/hosts"):
            return NODES
        if path.startswith("/check-ping"):
            return {"ok": 1, "request_id": "p1"}
        if path.startswith("/check-tcp"):
            return {"ok": 1, "request_id": "t1"}
        if path == "/check-result/p1":
            return {"ir1.node.check-host.net": [[["OK", 0.04, "x"]] * 4],
                    "ir3.node.check-host.net": [[["TIMEOUT", 3.0]] * 4]}
        if path == "/check-result/t1":
            return {"ir1.node.check-host.net": [{"time": 0.05, "address": "x"}],
                    "ir3.node.check-host.net": [{"error": "Connection refused"}]}
        raise AssertionError("unexpected path " + path)

    def test_full_check(self):
        with mock.patch.object(checkhost, "_get", self.fake_get):
            checker = checkhost.IranChecker(sleep=lambda _s: None)
            report = checker.check("203.0.113.5", [443])
        self.assertIsNone(report["error"])
        self.assertEqual(checkhost.summarize(report), (1, 2))
        first = report["nodes"][0]
        self.assertEqual(first["city"], "Tehran")
        self.assertTrue(first["tcp"][443]["ok"])
        self.assertFalse(report["nodes"][1]["tcp"][443]["ok"])

    def test_result_is_cached(self):
        calls = []

        def counting(path, timeout=15):
            calls.append(path)
            return self.fake_get(path)
        with mock.patch.object(checkhost, "_get", counting):
            checker = checkhost.IranChecker(sleep=lambda _s: None)
            checker.check("203.0.113.5", [])
            before = len(calls)
            checker.check("203.0.113.5", [])
            self.assertEqual(len(calls), before)
            checker.check("203.0.113.5", [], force=True)
            self.assertGreater(len(calls), before)

    def test_error_payload_raises(self):
        class Resp:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self):
                return b'{"error":"limit_exceeded"}'
        with mock.patch.object(checkhost.urllib.request, "urlopen", lambda *a, **k: Resp()):
            with self.assertRaises(checkhost.CheckHostError) as ctx:
                checkhost._get("/check-ping?host=1.1.1.1")
        self.assertIn("limit_exceeded", str(ctx.exception))

    def test_start_is_retried_after_a_transient_limit(self):
        attempts = {"ping": 0}

        def flaky(path, timeout=15):
            if path.startswith("/check-ping"):
                attempts["ping"] += 1
                if attempts["ping"] < 3:
                    raise checkhost.CheckHostError("limit_exceeded")
            return self.fake_get(path, timeout)
        waits = []
        with mock.patch.object(checkhost, "_get", flaky):
            checker = checkhost.IranChecker(sleep=waits.append)
            report = checker.check("203.0.113.5", [])
        self.assertIsNone(report["error"])
        self.assertEqual(attempts["ping"], 3)
        self.assertIn(checkhost.START_RETRY_WAIT, waits)

    def test_rate_limit_triggers_backoff(self):
        calls = []

        def limited(path, timeout=15):
            calls.append(path)
            if path.startswith("/nodes/hosts"):
                return NODES
            raise checkhost.CheckHostError("limit_exceeded")
        with mock.patch.object(checkhost, "_get", limited):
            checker = checkhost.IranChecker(sleep=lambda _s: None)
            first = checker.check("203.0.113.5", [])
            made = len(calls)
            second = checker.check("203.0.113.5", [], force=True)
        self.assertIn("limit", first["error"])
        self.assertIn("limit", second["error"])
        self.assertEqual(len(calls), made)  # no request while backing off

    def test_api_failure_is_reported_not_raised(self):
        def boom(path, timeout=15):
            raise checkhost.CheckHostError("network down")
        with mock.patch.object(checkhost, "_get", boom):
            checker = checkhost.IranChecker(sleep=lambda _s: None)
            report = checker.check("203.0.113.5", [])
        self.assertIn("network down", report["error"])
        self.assertEqual(report["nodes"], [])


if __name__ == "__main__":
    unittest.main()
