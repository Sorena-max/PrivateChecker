import json
import socket
import threading
import time
import unittest
from unittest import mock

from privatechecker import collectors, telegram_api
from privatechecker.telegram_api import Telegram, TelegramError
from tests.helpers import sample_data


class OpenSocketTests(unittest.TestCase):
    def test_prefers_ipv4_and_connects(self):
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        self.addCleanup(server.close)
        sock = telegram_api.open_socket("localhost", server.getsockname()[1])
        self.addCleanup(sock.close)
        self.assertEqual(sock.family, socket.AF_INET)

    def test_refused_port_fails_fast(self):
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()  # nothing listens here any more
        started = time.time()
        with self.assertRaises(OSError):
            telegram_api.open_socket("127.0.0.1", port)
        # bounded by the short connect timeout, never by a long request timeout
        self.assertLess(time.time() - started, telegram_api.CONNECT_TIMEOUT)


class CallTests(unittest.TestCase):
    def tg(self):
        return Telegram("123:SECRET")

    def test_success_returns_result(self):
        body = json.dumps({"ok": True, "result": {"username": "bot"}}).encode()
        with mock.patch.object(Telegram, "_post", return_value=body):
            self.assertEqual(self.tg().call("getMe"), {"username": "bot"})

    def test_api_error_carries_code_and_retry_after(self):
        body = json.dumps({"ok": False, "error_code": 429, "description": "slow down",
                           "parameters": {"retry_after": 7}}).encode()
        with mock.patch.object(Telegram, "_post", return_value=body):
            with self.assertRaises(TelegramError) as ctx:
                self.tg().call("sendMessage")
        self.assertEqual((ctx.exception.code, ctx.exception.retry_after), (429, 7))

    def test_network_error_never_leaks_the_token(self):
        err = OSError("failed to reach https://api.telegram.org/bot123:SECRET/getMe")
        with mock.patch.object(Telegram, "_post", side_effect=err):
            with self.assertRaises(TelegramError) as ctx:
                self.tg().call("getMe")
        self.assertNotIn("SECRET", str(ctx.exception))
        self.assertIn("<token>", str(ctx.exception))

    def test_garbage_response(self):
        with mock.patch.object(Telegram, "_post", return_value=b"<html>"):
            with self.assertRaises(TelegramError):
                self.tg().call("getMe")

    def test_long_poll_is_short_enough_to_recover_quickly(self):
        self.assertLessEqual(telegram_api.POLL_SECONDS, 25)
        seen = {}
        with mock.patch.object(Telegram, "call",
                               lambda self, method, params=None, timeout=25:
                               seen.update(timeout=timeout) or []):
            self.tg().get_updates(0)
        self.assertLessEqual(seen["timeout"], 35)


class SlowIranDoesNotBlockOtherSections(unittest.TestCase):
    """Regression: a minute-long Iran check used to freeze every button."""

    def test_quick_section_is_instant_while_iran_check_runs(self):
        class SlowChecker:
            def check(self, host, ports, force=False):
                time.sleep(1.5)
                return sample_data()["iran"]

        col = collectors.Collector(SlowChecker())
        cfg = {"sections": {}, "services": [], "iran": {"target": "203.0.113.5", "tcp_ports": []}}
        slow = threading.Thread(target=col.collect, args=(cfg, "iran"), daemon=True)
        slow.start()
        time.sleep(0.2)
        started = time.time()
        col.collect(cfg, only="memory")
        self.assertLess(time.time() - started, 0.8)
        slow.join()


if __name__ == "__main__":
    unittest.main()
