import json
import os
import socket
import tempfile
import threading
import unittest
from unittest import mock

from privatechecker import bot as botmod
from privatechecker import toolbox
from tests.helpers import FRIEND, OWNER
from tests.test_bot import BotTestCase, callback, message


class FakeAgent:
    """Stands in for the PrivateToolBox agent socket."""

    def __init__(self, replies=None):
        self.requests = []
        self.replies = replies or {}

    def call(self, request, timeout=900):
        self.requests.append((request, timeout))
        return self.replies.get(request["cmd"], {"ok": True, "output": "all good"})


class ToolboxTestCase(BotTestCase):
    def setUp(self, **kw):
        super().setUp(**kw)
        self.agent = FakeAgent()
        for patcher in (mock.patch.object(toolbox, "available", return_value=True),
                        mock.patch.object(toolbox, "call", self.agent.call)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def texts(self):
        return [m[1] for m in self.tg.sent]

    def buttons(self, index=-1):
        markup = self.tg.sent[index][2] or {"inline_keyboard": []}
        return [b["callback_data"] for row in markup["inline_keyboard"] for b in row]


class ButtonVisibilityTests(ToolboxTestCase):
    def main_buttons(self, uid):
        self.tg.sent.clear()
        self.send(message(uid, "/start"))
        return self.buttons(0)

    def test_owner_sees_the_button_when_the_bridge_exists(self):
        self.assertIn("tb:menu", self.main_buttons(OWNER))

    def test_viewers_never_see_it(self):
        self.setUp(users=[FRIEND])
        self.assertNotIn("tb:menu", self.main_buttons(FRIEND))

    def test_still_shown_to_the_owner_when_toolbox_is_not_set_up(self):
        with mock.patch.object(toolbox, "available", return_value=False):
            self.assertIn("tb:menu", self.main_buttons(OWNER))


class OwnerOnlyTests(ToolboxTestCase):
    def test_a_viewer_cannot_run_anything_even_with_a_crafted_callback(self):
        self.setUp(users=[FRIEND])
        for data in ("tb:scan", "tb:do:vpn", "tb:undo:yes", "tb:keep", "tb:plan:vpn"):
            self.send(callback(FRIEND, data))
        self.assertEqual(self.agent.requests, [])
        self.assertEqual(self.tg.sent, [])

    def test_a_stranger_gets_nothing(self):
        self.send(callback(9999, "tb:do:vpn"))
        self.assertEqual(self.agent.requests, [])

    def test_commands_need_the_bridge(self):
        with mock.patch.object(toolbox, "available", return_value=False):
            self.send(callback(OWNER, "tb:scan"))
            self.send(callback(OWNER, "tb:do:vpn"))
        self.assertEqual(self.agent.requests, [])
        self.assertIn("integrate", self.tg.answers[-1][1])


class SimpleCommandTests(ToolboxTestCase):
    def test_menus_open(self):
        self.send(callback(OWNER, "tb:menu"))
        self.send(callback(OWNER, "tb:profiles"))
        self.assertEqual(len(self.tg.edited), 2)

    def test_scan_is_sent_as_preformatted_text(self):
        self.agent.replies["scan"] = {"ok": True, "output": "Score 40 <b>&"}
        self.send(callback(OWNER, "tb:scan"))
        self.assertEqual(self.agent.requests[0][0], {"cmd": "scan", "lang": "en"})
        self.assertEqual(self.texts()[0], "<pre>Score 40 &lt;b&gt;&amp;</pre>")

    def test_the_request_uses_the_bot_language(self):
        self.cfg.update(lambda d: d.__setitem__("language", "fa"))
        self.send(callback(OWNER, "tb:scan"))
        self.assertEqual(self.agent.requests[0][0]["lang"], "fa")

    def test_verify_with_iran(self):
        self.send(callback(OWNER, "tb:iran"))
        self.assertEqual(self.agent.requests[0][0], {"cmd": "verify", "iran": True, "lang": "en"})

    def test_history_and_keep(self):
        self.send(callback(OWNER, "tb:hist"))
        self.send(callback(OWNER, "tb:keep"))
        self.assertEqual([r[0]["cmd"] for r in self.agent.requests], ["history", "confirm"])

    def test_long_output_is_split_into_telegram_sized_messages(self):
        self.agent.replies["scan"] = {"ok": True, "output": "\n".join("line %d" % i for i in range(2000))}
        self.send(callback(OWNER, "tb:scan"))
        self.assertGreater(len(self.tg.sent), 1)
        self.assertTrue(all(len(m[1]) < 4096 for m in self.tg.sent))

    def test_empty_output(self):
        self.agent.replies["scan"] = {"ok": True, "output": ""}
        self.send(callback(OWNER, "tb:scan"))
        self.assertIn("no output", self.texts()[0])

    def test_failures_are_reported(self):
        self.agent.replies["scan"] = {"ok": False, "code": 2, "output": "boom"}
        self.send(callback(OWNER, "tb:scan"))
        self.assertIn("failed (2)", self.texts()[-1])

    def test_busy_agent(self):
        self.agent.replies["scan"] = {"ok": False, "error": "busy"}
        self.send(callback(OWNER, "tb:scan"))
        self.assertIn("Another PrivateToolBox job", self.texts()[0])

    def test_a_broken_connection_is_reported_not_raised(self):
        with mock.patch.object(toolbox, "call", return_value={"ok": False, "error": "refused"}):
            self.send(callback(OWNER, "tb:scan"))
        self.assertIn("refused", self.texts()[0])


class ApplyFlowTests(ToolboxTestCase):
    def test_preview_comes_before_apply_and_asks(self):
        self.agent.replies["plan"] = {"ok": True, "output": "What will change"}
        self.send(callback(OWNER, "tb:plan:vpn"))
        self.assertEqual(self.agent.requests[0][0]["cmd"], "plan")
        self.assertEqual(self.buttons(), ["tb:do:vpn", "tb:menu"])
        self.assertEqual([r[0]["cmd"] for r in self.agent.requests], ["plan"])    # nothing applied yet

    def test_unknown_profiles_are_ignored(self):
        for data in ("tb:plan:../etc", "tb:do:evil", "tb:plan:--yes", "tb:do:"):
            self.send(callback(OWNER, data))
        self.assertEqual(self.agent.requests, [])

    def test_apply_arms_the_keep_prompt(self):
        self.agent.replies["apply"] = {"ok": True, "output": "Applying", "pending": "20260101-120000"}
        self.send(callback(OWNER, "tb:do:bot"))
        request = self.agent.requests[0][0]
        self.assertEqual((request["cmd"], request["profile"], request["rollback"]), ("apply", "bot", 180))
        self.assertEqual(self.buttons(), ["tb:keep", "tb:undo:yes"])
        self.assertIn("NEW SSH session", self.texts()[-1])

    def test_no_keep_prompt_when_nothing_is_pending(self):
        self.agent.replies["apply"] = {"ok": True, "output": "Nothing to do", "pending": None}
        self.send(callback(OWNER, "tb:do:bot"))
        self.assertNotIn("NEW SSH", self.texts()[-1])

    def test_failed_apply_has_no_keep_prompt(self):
        self.agent.replies["apply"] = {"ok": False, "code": 1, "output": "rolled back", "pending": None}
        self.send(callback(OWNER, "tb:do:vpn"))
        self.assertIn("failed", self.texts()[-1])
        self.assertNotIn("tb:keep", self.buttons())

    def test_undo_asks_first(self):
        self.send(callback(OWNER, "tb:undo"))
        self.assertEqual(self.agent.requests, [])
        self.assertEqual(self.buttons(), ["tb:undo:yes", "tb:menu"])
        self.send(callback(OWNER, "tb:undo:yes"))
        self.assertEqual(self.agent.requests[0][0]["cmd"], "undo")

    def test_apply_has_a_long_timeout(self):
        self.send(callback(OWNER, "tb:do:vpn"))
        self.assertGreaterEqual(self.agent.requests[0][1], 600)

class FakeHelper:
    def __init__(self, reply=None):
        self.calls = []
        self.reply = reply or {"ok": True, "output": "Installed"}

    def call(self, cmd, timeout=900):
        self.calls.append((cmd, timeout))
        return self.reply


class SetupTestCase(ToolboxTestCase):
    """PrivateToolBox missing or not connected."""

    def configure(self, installed=False, helper_on=True, reply=None):
        self.helper = FakeHelper(reply)
        for patcher in (mock.patch.object(toolbox, "available", return_value=False),
                        mock.patch.object(toolbox, "installed", return_value=installed),
                        mock.patch.object(toolbox, "helper_available", return_value=helper_on),
                        mock.patch.object(toolbox, "helper_call", self.helper.call)):
            patcher.start()
            self.addCleanup(patcher.stop)


class NotInstalledTests(SetupTestCase):
    def test_tapping_the_button_offers_to_install(self):
        self.configure()
        self.send(callback(OWNER, "tb:menu"))
        self.assertIn("not installed", self.texts()[0])
        self.assertEqual(self.buttons(), ["tb:install", "m:main"])
        self.assertEqual(self.helper.calls, [])

    def test_install_asks_before_doing_anything(self):
        self.configure()
        self.send(callback(OWNER, "tb:install"))
        self.assertEqual(self.helper.calls, [])
        self.assertIn(botmod.helper.TOOLBOX_REF, self.texts()[0])
        self.assertIn("as root", self.texts()[0])
        self.assertEqual(self.buttons(), ["tb:install:yes", "m:main"])

    def test_confirming_runs_the_helper(self):
        self.configure()
        self.send(callback(OWNER, "tb:install:yes"))
        self.assertEqual([c[0] for c in self.helper.calls], ["install_toolbox"])
        self.assertIn("ready", self.texts()[-1])

    def test_a_failed_install_is_reported(self):
        self.configure(reply={"ok": False, "output": "download failed"})
        self.send(callback(OWNER, "tb:install:yes"))
        self.assertIn("download failed", " ".join(self.texts()))
        self.assertIn("did not finish", self.texts()[-1])

    def test_the_pending_flag_is_cleared_after_the_job(self):
        self.configure()
        self.send(callback(OWNER, "tb:install:yes"))
        self.assertFalse(self.state.snapshot()["toolbox_pending"])

    def test_without_the_helper_it_explains_how_to_install_by_hand(self):
        self.configure(helper_on=False)
        self.send(callback(OWNER, "tb:menu"))
        self.assertIn("install.sh", self.texts()[0])
        self.assertIn("enable-install", self.texts()[0])
        self.assertEqual(self.buttons(), [])
        self.send(callback(OWNER, "tb:install:yes"))
        self.assertEqual(self.helper.calls, [])

    def test_viewers_cannot_trigger_an_install(self):
        self.setUp(users=[FRIEND])
        self.configure()
        for data in ("tb:menu", "tb:install", "tb:install:yes", "tb:enable"):
            self.send(callback(FRIEND, data))
        self.assertEqual(self.helper.calls, [])
        self.assertEqual(self.tg.sent, [])


class InstalledButNotConnectedTests(SetupTestCase):
    def test_offers_to_connect(self):
        self.configure(installed=True)
        self.send(callback(OWNER, "tb:menu"))
        self.assertIn("not connected", self.texts()[0])
        self.assertEqual(self.buttons(), ["tb:enable", "m:main"])

    def test_connecting_runs_only_the_bridge_step(self):
        self.configure(installed=True)
        self.send(callback(OWNER, "tb:enable"))
        self.assertEqual([c[0] for c in self.helper.calls], ["enable_bridge"])

    def test_manual_hint_without_the_helper(self):
        self.configure(installed=True, helper_on=False)
        self.send(callback(OWNER, "tb:menu"))
        self.assertIn("privatetoolbox integrate", self.texts()[0])


class RestartFollowUpTests(SetupTestCase):
    def test_after_the_restart_the_owner_hears_how_it_went(self):
        self.configure()
        self.state.update(lambda d: d.__setitem__("toolbox_pending", 123.0))
        with mock.patch.object(toolbox, "available", return_value=True):
            self.bot.startup()
        self.assertTrue(any("ready" in t for t in self.texts()))
        self.assertFalse(self.state.snapshot()["toolbox_pending"])

    def test_a_failed_install_is_reported_after_the_restart(self):
        self.configure()
        self.state.update(lambda d: d.__setitem__("toolbox_pending", 123.0))
        self.bot.startup()
        self.assertTrue(any("did not finish" in t for t in self.texts()))

    def test_nothing_extra_on_a_normal_start(self):
        self.configure()
        self.bot.startup()
        self.assertFalse(any("PrivateToolBox is ready" in t for t in self.texts()))


class ClientTests(unittest.TestCase):
    def test_unix_socket_round_trip(self):
        if not hasattr(socket, "AF_UNIX"):
            self.skipTest("no unix sockets here")
        path = os.path.join(tempfile.mkdtemp(), "agent.sock")
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(path)
        server.listen(1)
        seen = {}

        def serve():
            conn, _ = server.accept()
            seen["request"] = json.loads(conn.recv(65536).decode())
            conn.sendall(b'{"ok": true, "output": "hi"}\n')
            conn.close()
        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        with mock.patch.dict(os.environ, {"PRIVATETOOLBOX_SOCKET": path}):
            self.assertTrue(toolbox.available())
            reply = toolbox.call({"cmd": "scan"}, timeout=5)
        thread.join(5)
        server.close()
        self.assertEqual(reply, {"ok": True, "output": "hi"})
        self.assertEqual(seen["request"], {"cmd": "scan"})

    def test_missing_socket_is_an_error_not_an_exception(self):
        with mock.patch.dict(os.environ, {"PRIVATETOOLBOX_SOCKET": "/nonexistent/agent.sock"}):
            self.assertFalse(toolbox.available())
            self.assertFalse(toolbox.call({"cmd": "scan"})["ok"])

    def test_garbage_reply(self):
        with mock.patch.object(toolbox, "_exchange", return_value=b"not json"):
            self.assertFalse(toolbox.call({"cmd": "scan"})["ok"])
        with mock.patch.object(toolbox, "_exchange", return_value=b"[1, 2]"):
            self.assertFalse(toolbox.call({"cmd": "scan"})["ok"])


if __name__ == "__main__":
    unittest.main()
