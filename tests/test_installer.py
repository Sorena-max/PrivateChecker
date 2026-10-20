import os
import re
import shutil
import subprocess
import unittest

from privatechecker import __version__
from privatechecker.i18n import T

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INSTALLER = os.path.join(ROOT, "install.sh")


def installer_text():
    with open(INSTALLER, encoding="utf-8") as fh:
        return fh.read()


class InstallerTests(unittest.TestCase):
    def test_version_matches_the_package(self):
        found = re.search(r'^SC_VERSION="([^"]+)"', installer_text(), re.M)
        self.assertIsNotNone(found)
        self.assertEqual(found.group(1), __version__)

    def test_uses_lf_line_endings(self):
        with open(INSTALLER, "rb") as fh:
            self.assertNotIn(b"\r", fh.read())

    def test_credits_the_project_and_states_it_is_free(self):
        text = installer_text()
        self.assertIn("GitHub:", text)
        self.assertIn("Sorena-max", text)
        self.assertIn("completely free", text)

    def test_terminal_text_has_no_persian(self):
        # Terminals shape Persian badly, so the installer UI stays in English.
        # Persian is allowed only in the message sent to Telegram.
        persian = re.compile("[؀-ۿ]")
        for number, line in enumerate(installer_text().splitlines(), 1):
            if persian.search(line):
                self.assertIn("✅ پرایوت چکر", line, "Persian on line %d" % number)

    def test_animation_is_off_for_automation(self):
        text = installer_text()
        self.assertIn("--fast", text)
        self.assertIn('if [ "$FAST" -eq 0 ] && [ "$NON_INTERACTIVE" -eq 0 ]; then SLOW=1; fi', text)

    def test_script_is_parsed_in_full_before_it_runs(self):
        # `curl | bash` reads the script incrementally; a trailing `main "$@"`
        # guarantees nothing is executed from a half-downloaded file.
        self.assertEqual(installer_text().rstrip().splitlines()[-1], 'main "$@"')

    @unittest.skipUnless(shutil.which("bash"), "bash not available")
    def test_syntax_is_valid(self):
        result = subprocess.run(["bash", "-n", INSTALLER], stderr=subprocess.PIPE,
                                universal_newlines=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(shutil.which("bash"), "bash not available")
    def test_help_works_without_root(self):
        result = subprocess.run(["bash", INSTALLER, "--help"], stdout=subprocess.PIPE,
                                universal_newlines=True)
        self.assertEqual(result.returncode, 0)
        self.assertIn("--non-interactive", result.stdout)


class BotMessageTests(unittest.TestCase):
    def test_free_notice_and_link_are_in_both_languages(self):
        for lang in ("fa", "en"):
            footer = T[lang]["footer"]
            self.assertIn("https://github.com/Sorena-max/PrivateChecker", footer)
        self.assertIn("رایگان", T["fa"]["footer"])
        self.assertIn("free", T["en"]["footer"])


if __name__ == "__main__":
    unittest.main()
