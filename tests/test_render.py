import re
import unittest

from privatechecker import config, render
from privatechecker.i18n import T, t
from privatechecker.telegram_api import MAX_MESSAGE, Telegram, pack
from tests.helpers import sample_data


def placeholders(text):
    return set(re.findall(r"\{(\w+)\}", text))


class I18nTests(unittest.TestCase):
    def test_both_languages_have_identical_keys(self):
        self.assertEqual(set(T["en"]), set(T["fa"]))

    def test_placeholders_match_between_languages(self):
        for key in T["en"]:
            self.assertEqual(placeholders(T["en"][key]), placeholders(T["fa"][key]), key)

    def test_every_section_has_a_title(self):
        for name in config.SECTIONS:
            self.assertIn("sec_" + name, T["en"])

    def test_unknown_key_returns_key(self):
        self.assertEqual(t("en", "no_such_key"), "no_such_key")


class HelperTests(unittest.TestCase):
    def test_human_bytes(self):
        self.assertEqual(render.human_bytes(512), "512 B")
        self.assertEqual(render.human_bytes(1536), "1.5 KB")
        self.assertEqual(render.human_bytes(5 * 1024 ** 3), "5.0 GB")

    def test_duration(self):
        self.assertEqual(render.human_duration(90061, "en"), "1 d 1 h 1 m")
        self.assertEqual(render.human_duration(30, "en"), "0 m")
        self.assertIn("روز", render.human_duration(90061, "fa"))

    def test_minutes_label(self):
        self.assertEqual(render.minutes_label(30, "en"), "30 min")
        self.assertEqual(render.minutes_label(120, "en"), "2 h")

    def test_bar_bounds(self):
        self.assertEqual(render.bar(0), "░" * 10)
        self.assertEqual(render.bar(100), "█" * 10)
        self.assertEqual(len(render.bar(150)), 10)

    def test_level(self):
        self.assertEqual(render.level(10, 90), "🟢")
        self.assertEqual(render.level(92, 90), "🟡")
        self.assertEqual(render.level(99, 90), "🔴")


class ReportTests(unittest.TestCase):
    def cfg(self):
        return config.normalize({"owner_id": 1})

    def test_report_contains_every_collected_section(self):
        for lang in ("en", "fa"):
            parts = render.build_report(sample_data(), self.cfg(), lang, "box")
            text = "\n".join(parts)
            for name in config.SECTIONS:
                self.assertIn(t(lang, "sec_" + name), text, (lang, name))

    def test_all_good_status(self):
        data = sample_data()
        data["updates"]["security"] = 0
        parts = render.build_report(data, self.cfg(), "en", "box")
        self.assertIn(t("en", "status_ok"), parts[0])

    def test_problems_are_listed(self):
        data = sample_data()
        data["memory"]["pct"] = 97.0
        data["services"]["failed"] = ["nginx.service"]
        data["iran"]["nodes"][0]["ping"]["ok"] = 0
        parts = render.build_report(data, self.cfg(), "en", "box")
        head = parts[0]
        self.assertIn("RAM at 97%", head)
        self.assertIn("nginx.service", head)
        self.assertIn("unreachable from Iran", head)
        self.assertIn("🔴", head)

    def test_html_is_escaped(self):
        data = sample_data()
        data["services"]["failed"] = ["<script>alert(1)</script>"]
        text = "\n".join(render.build_report(data, self.cfg(), "en", "<b>x</b>"))
        self.assertNotIn("<script>", text)
        self.assertIn("&lt;script&gt;", text)

    def test_iran_error_is_shown(self):
        data = {"iran": {"target": "x", "nodes": [], "error": "HTTP 429"}}
        parts = render.build_report(data, self.cfg(), "en", "box")
        self.assertIn("HTTP 429", "\n".join(parts))

    def test_missing_docker_is_left_out_of_reports(self):
        data = sample_data()
        data["docker"] = {"available": False, "reason": "not-installed"}
        text = "\n".join(render.build_report(data, self.cfg(), "en", "box"))
        self.assertNotIn("Docker", text)

    def test_unavailable_docker_is_explained(self):
        text = render.render_docker({"available": False, "reason": "no-access"}, "en", self.cfg())
        self.assertIn("not accessible", text)

    def test_strip_html(self):
        self.assertEqual(render.strip_html("<b>a &amp; b</b> <code>c</code>"), "a & b c")


class PackTests(unittest.TestCase):
    def test_small_parts_merge(self):
        self.assertEqual(pack(["a", "b"]), ["a\n\nb"])

    def test_large_parts_split(self):
        parts = ["x" * 3000, "y" * 3000]
        packed = pack(parts)
        self.assertEqual(len(packed), 2)
        self.assertTrue(all(len(m) <= MAX_MESSAGE for m in packed))

    def test_oversized_single_part_is_split_by_lines(self):
        part = "\n".join("line%d" % i for i in range(2000))
        self.assertTrue(all(len(m) <= MAX_MESSAGE for m in pack([part])))

    def test_empty_parts_ignored(self):
        self.assertEqual(pack(["", None, "a"]), ["a"])


class TelegramTests(unittest.TestCase):
    def test_token_is_redacted(self):
        tg = Telegram("123:SECRETTOKEN")
        self.assertEqual(tg.redact("failed https://x/bot123:SECRETTOKEN/getMe"),
                         "failed https://x/bot<token>/getMe")


if __name__ == "__main__":
    unittest.main()
