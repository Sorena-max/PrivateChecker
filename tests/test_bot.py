import time
import unittest

from privatechecker import config
from privatechecker.bot import Bot
from privatechecker.i18n import t
from tests.helpers import (FRIEND, OWNER, STRANGER, FakeCollector,
                           FakeTelegram, make_config)


def message(uid, text, chat_type="private", chat_id=None):
    return {"message": {"message_id": 1, "from": {"id": uid},
                        "chat": {"id": chat_id or uid, "type": chat_type},
                        "text": text}}


def callback(uid, data, message_id=7):
    return {"callback_query": {"id": "cb", "from": {"id": uid}, "data": data,
                               "message": {"message_id": message_id, "chat": {"id": uid}}}}


class BotTestCase(unittest.TestCase):
    def setUp(self, **overrides):
        self.cfg, self.state = make_config(language="en", **overrides)
        self.tg = FakeTelegram()
        self.col = FakeCollector()
        self.bot = Bot(self.cfg, self.state, self.tg, self.col, sleep=lambda _s: None)
        # run background jobs inline so tests are deterministic
        self.bot._spawn = lambda fn: fn()

    def data(self):
        return self.cfg.snapshot()

    def send(self, update):
        self.bot.handle_update(update)


class AuthorizationTests(BotTestCase):
    def test_stranger_gets_no_reply_at_all(self):
        for text in ("/start", "/report", "hello"):
            self.send(message(STRANGER, text))
        self.send(callback(STRANGER, "r:full"))
        self.assertEqual(self.tg.sent, [])
        self.assertEqual(self.tg.edited, [])
        self.assertEqual(self.col.collect_calls, [])

    def test_stranger_cannot_change_settings(self):
        self.send(callback(STRANGER, "iv:set:5"))
        self.send(callback(STRANGER, "lg:set:fa"))
        self.assertEqual(self.data()["interval_min"], 30)
        self.assertEqual(self.data()["language"], "en")

    def test_group_chats_are_ignored_even_for_owner(self):
        self.send(message(OWNER, "/start", chat_type="supergroup", chat_id=-100123))
        self.assertEqual(self.tg.sent, [])

    def test_owner_start_opens_panel(self):
        self.send(message(OWNER, "/start"))
        chat_id, text, markup = self.tg.sent[0]
        self.assertEqual(chat_id, OWNER)
        self.assertIn("PrivateChecker", text)
        flat = [b["callback_data"] for row in markup["inline_keyboard"] for b in row]
        self.assertIn("r:full", flat)
        self.assertIn("us:menu", flat)

    def test_panel_always_shows_project_name_and_github_link(self):
        for lang in ("en", "fa"):
            self.cfg.update(lambda d, lang=lang: d.__setitem__("language", lang))
            self.tg.sent.clear()
            self.send(message(OWNER, "/start"))
            text = self.tg.sent[0][1]
            self.assertIn("Private Tool", text)
            self.assertIn("https://github.com/Sorena-max/PrivateChecker", text)

    def test_startup_message_is_localised_and_carries_the_notice(self):
        self.cfg.update(lambda d: d.__setitem__("language", "fa"))
        self.bot.startup()
        chat_id, text, _ = self.tg.sent[0]
        self.assertEqual(chat_id, OWNER)
        self.assertIn("پرایوت چکر", text)
        self.assertIn("رایگان", text)
        self.assertIn("github.com/Sorena-max/PrivateChecker", text)
        self.assertNotIn("{footer}", text)

    def test_start_with_bot_suffix(self):
        self.send(message(OWNER, "/start@my_bot"))
        self.assertEqual(len(self.tg.sent), 1)

    def test_added_user_can_use_bot_but_not_manage_users(self):
        self.setUp(users=[FRIEND])
        self.send(message(FRIEND, "/start"))
        markup = self.tg.sent[0][2]
        flat = [b["callback_data"] for row in markup["inline_keyboard"] for b in row]
        self.assertNotIn("us:menu", flat)
        self.send(callback(FRIEND, "us:add"))
        self.send(message(FRIEND, "12345"))
        self.assertEqual(self.data()["users"], [FRIEND])


class ReportTests(BotTestCase):
    def test_report_command_sends_full_report(self):
        self.send(message(OWNER, "/report"))
        text = "\n".join(m[1] for m in self.tg.sent)
        self.assertIn("Server report", text)
        self.assertEqual(self.col.collect_calls, [None])

    def test_quick_section_button(self):
        self.send(callback(OWNER, "s:disk"))
        self.assertEqual(self.col.collect_calls, ["disk"])
        self.assertIn("Disk", self.tg.sent[0][1])

    def test_iran_now_button(self):
        self.send(callback(OWNER, "ir:now"))
        self.assertEqual(self.col.collect_calls, ["iran"])
        self.assertIn("Iran", self.tg.sent[0][1])

    def test_a_tap_runs_a_fresh_test_but_the_schedule_may_reuse_one(self):
        self.send(callback(OWNER, "ir:now"))
        self.send(callback(OWNER, "s:iran"))
        self.send(callback(OWNER, "r:full"))
        self.send(message(OWNER, "/report"))
        self.assertEqual(self.col.fresh_calls, [True, True, True, True])
        self.col.fresh_calls.clear()
        self.bot.scheduler_tick(1000.0)
        self.bot.scheduler_tick(1000.0 + 31 * 60)
        self.assertEqual(self.col.fresh_calls, [False])

    def test_unknown_section_is_ignored(self):
        self.send(callback(OWNER, "s:bogus"))
        self.assertEqual(self.col.collect_calls, [])
        self.assertEqual(self.tg.sent, [])


class IntervalTests(BotTestCase):
    def test_presets(self):
        self.send(callback(OWNER, "iv:set:120"))
        self.assertEqual(self.data()["interval_min"], 120)

    def test_custom_interval_flow(self):
        self.send(callback(OWNER, "iv:custom"))
        self.send(message(OWNER, "45"))
        self.assertEqual(self.data()["interval_min"], 45)

    def test_custom_interval_rejects_out_of_range(self):
        for bad in ("4", "1201", "abc", "-5", "3.5"):
            self.send(callback(OWNER, "iv:custom"))
            self.send(message(OWNER, bad))
            self.assertEqual(self.data()["interval_min"], 30, bad)

    def test_range_edges_are_accepted(self):
        for ok in ("5", "1200"):
            self.send(callback(OWNER, "iv:custom"))
            self.send(message(OWNER, ok))
            self.assertEqual(self.data()["interval_min"], int(ok))

    def test_pause_and_resume(self):
        self.send(callback(OWNER, "iv:toggle"))
        self.assertFalse(self.data()["reports_enabled"])
        self.send(callback(OWNER, "iv:toggle"))
        self.assertTrue(self.data()["reports_enabled"])


class SettingsTests(BotTestCase):
    def test_section_toggle(self):
        before = self.data()["sections"]["ports"]
        self.send(callback(OWNER, "sec:t:ports"))
        self.assertNotEqual(self.data()["sections"]["ports"], before)

    def test_invalid_section_toggle_is_ignored(self):
        snapshot = self.data()["sections"]
        self.send(callback(OWNER, "sec:t:bogus"))
        self.assertEqual(self.data()["sections"], snapshot)

    def test_language_switch(self):
        self.send(callback(OWNER, "lg:set:fa"))
        self.assertEqual(self.data()["language"], "fa")
        self.send(callback(OWNER, "lg:set:xx"))
        self.assertEqual(self.data()["language"], "fa")

    def test_alert_thresholds_step_and_clamp(self):
        self.send(callback(OWNER, "al:cpu:5"))
        self.assertEqual(self.data()["alerts"]["cpu"], 95)
        for _ in range(5):
            self.send(callback(OWNER, "al:cpu:5"))
        self.assertEqual(self.data()["alerts"]["cpu"], 99)
        for _ in range(20):
            self.send(callback(OWNER, "al:mem:-5"))
        self.assertEqual(self.data()["alerts"]["mem"], 50)

    def test_alert_toggles(self):
        self.send(callback(OWNER, "al:toggle"))
        self.assertFalse(self.data()["alerts"]["enabled"])
        self.send(callback(OWNER, "al:iran"))
        self.assertFalse(self.data()["alerts"]["iran"])

    def test_owner_adds_and_removes_user(self):
        self.send(callback(OWNER, "us:add"))
        self.send(message(OWNER, str(FRIEND)))
        self.assertEqual(self.data()["users"], [FRIEND])
        self.send(callback(OWNER, "us:del:%d" % FRIEND))
        self.assertEqual(self.data()["users"], [])

    def test_bad_user_id_is_rejected(self):
        self.send(callback(OWNER, "us:add"))
        self.send(message(OWNER, "not-a-number"))
        self.assertEqual(self.data()["users"], [])

    def test_owner_cannot_be_added_as_extra_user(self):
        self.send(callback(OWNER, "us:add"))
        self.send(message(OWNER, str(OWNER)))
        self.assertEqual(self.data()["users"], [])

    def test_added_user_then_works(self):
        self.send(callback(OWNER, "us:add"))
        self.send(message(OWNER, str(FRIEND)))
        self.send(message(FRIEND, "/start"))
        self.assertEqual(self.tg.sent[-1][0], FRIEND)

    def test_service_add_validates_name(self):
        self.bot._unit_exists = lambda name: name == "nginx"
        self.send(callback(OWNER, "sv:add"))
        self.send(message(OWNER, "nginx"))
        self.send(callback(OWNER, "sv:add"))
        self.send(message(OWNER, "missing"))
        self.send(callback(OWNER, "sv:add"))
        self.send(message(OWNER, "bad name; rm -rf /"))
        self.assertEqual(self.data()["services"], ["nginx"])
        self.send(callback(OWNER, "sv:del:0"))
        self.assertEqual(self.data()["services"], [])

    def test_iran_settings(self):
        self.send(callback(OWNER, "ir:target"))
        self.send(message(OWNER, "example.com"))
        self.send(callback(OWNER, "ir:ports"))
        self.send(message(OWNER, "443, 80"))
        iran = self.data()["iran"]
        self.assertEqual((iran["target"], iran["tcp_ports"]), ("example.com", [443, 80]))
        self.send(callback(OWNER, "ir:ports"))
        self.send(message(OWNER, "99999"))
        self.assertEqual(self.data()["iran"]["tcp_ports"], [443, 80])
        self.send(callback(OWNER, "ir:auto"))
        self.assertEqual(self.data()["iran"]["target"], "")

    def test_iran_target_rejects_shell_characters(self):
        self.send(callback(OWNER, "ir:target"))
        self.send(message(OWNER, "1.2.3.4; reboot"))
        self.assertEqual(self.data()["iran"]["target"], "")

    def test_cancel_clears_pending_input(self):
        self.send(callback(OWNER, "iv:custom"))
        self.send(message(OWNER, "/cancel"))
        self.send(message(OWNER, "45"))
        self.assertEqual(self.data()["interval_min"], 30)


class SchedulerTests(BotTestCase):
    def test_first_tick_only_arms_the_timer(self):
        self.bot.scheduler_tick(1000.0)
        self.assertEqual(self.tg.sent, [])
        self.assertEqual(self.state.snapshot()["last_report_ts"], 1000.0)

    def test_report_is_sent_when_interval_elapsed(self):
        self.bot.scheduler_tick(1000.0)
        self.bot.scheduler_tick(1000.0 + 29 * 60)
        self.assertEqual(self.tg.sent, [])
        self.bot.scheduler_tick(1000.0 + 30 * 60)
        self.assertTrue(self.tg.sent)
        self.assertEqual({m[0] for m in self.tg.sent}, {OWNER})

    def test_report_goes_to_every_authorised_user(self):
        self.setUp(users=[FRIEND])
        self.bot.scheduler_tick(1000.0)
        self.bot.scheduler_tick(1000.0 + 31 * 60)
        self.assertEqual({m[0] for m in self.tg.sent}, {OWNER, FRIEND})

    def test_changing_interval_restarts_the_clock(self):
        self.bot.scheduler_tick(1000.0)
        self.send(callback(OWNER, "iv:set:5"))
        last = self.state.snapshot()["last_report_ts"]
        self.assertGreater(last, 1000.0)
        self.assertLess(time.time() - last, 5)

    def test_paused_reports_are_not_sent(self):
        self.send(callback(OWNER, "iv:toggle"))
        self.tg.sent.clear()
        self.bot.scheduler_tick(10 ** 10)
        self.assertEqual(self.tg.sent, [])


class AlertTests(BotTestCase):
    def tick(self, now):
        self.bot.alerts.tick(now)

    def alerts_text(self):
        return [m[1] for m in self.tg.sent]

    def test_disk_alert_fires_once_then_recovers(self):
        self.col.data["disk"][0]["pct"] = 97.0
        self.tick(1000)
        self.assertEqual(len(self.tg.sent), 1)
        self.assertIn("Disk almost full", self.tg.sent[0][1])
        self.tick(1060)                      # still bad, inside cooldown -> silent
        self.assertEqual(len(self.tg.sent), 1)
        self.col.data["disk"][0]["pct"] = 40.0
        self.tick(1120)
        self.assertEqual(len(self.tg.sent), 2)
        self.assertIn("back to normal", self.tg.sent[1][1])

    def test_alert_repeats_after_cooldown(self):
        self.col.data["disk"][0]["pct"] = 97.0
        self.tick(1000)
        self.tick(1000 + 61 * 60)
        self.assertEqual(len(self.tg.sent), 2)

    def test_memory_needs_two_consecutive_checks(self):
        self.col.data["memory"]["pct"] = 99.0
        self.tick(1000)
        self.assertEqual(self.tg.sent, [])
        self.tick(1060)
        self.assertEqual(len(self.tg.sent), 1)

    def test_single_spike_never_alerts(self):
        self.col.data["memory"]["pct"] = 99.0
        self.tick(1000)
        self.col.data["memory"]["pct"] = 10.0
        self.tick(1060)
        self.col.data["memory"]["pct"] = 99.0
        self.tick(1120)
        self.assertEqual(self.tg.sent, [])

    def test_failed_service_alert(self):
        self.col.data["services"]["failed"] = ["nginx.service"]
        self.tick(1000)
        self.tick(1060)
        self.assertIn("nginx.service", self.tg.sent[-1][1])

    def test_iran_unreachable_alert(self):
        self.col.data["iran"]["nodes"][0]["ping"] = {"ok": 0, "total": 4, "avg_ms": None}
        self.tick(1000)
        self.bot.alerts._next_iran = 0
        self.tick(1000 + 15 * 60)
        self.assertTrue(any("NOT reachable from Iran" in m for m in self.alerts_text()))

    def test_disabled_alerts_stay_silent(self):
        self.send(callback(OWNER, "al:toggle"))
        self.col.data["disk"][0]["pct"] = 99.0
        self.tick(1000)
        self.assertEqual(self.tg.sent, [])

    def test_alerts_reach_all_authorised_users(self):
        self.setUp(users=[FRIEND])
        self.col.data["disk"][0]["pct"] = 99.0
        self.tick(1000)
        self.assertEqual({m[0] for m in self.tg.sent}, {OWNER, FRIEND})


if __name__ == "__main__":
    unittest.main()
