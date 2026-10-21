import io
import os
import tarfile
import tempfile
import unittest
from unittest import mock

from privatechecker import helper


def make_archive(entries, top="PrivateToolBox-0.1.1"):
    """A gzip tarball of (name, bytes) files under one top directory."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        directory = tarfile.TarInfo(top)
        directory.type = tarfile.DIRTYPE
        tar.addfile(directory)
        for name, data in entries:
            info = tarfile.TarInfo("%s/%s" % (top, name) if top else name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


GOOD = [("install.sh", b"#!/bin/bash\n"), ("privatetoolbox/__init__.py", b"")]


class Runner:
    def __init__(self, results=None):
        self.calls = []
        self.results = list(results or [])

    def __call__(self, argv, timeout=600):
        self.calls.append(argv)
        return self.results.pop(0) if self.results else (0, "ok")


class ExtractTests(unittest.TestCase):
    def test_good_archive(self):
        top = helper.safe_extract(make_archive(GOOD), tempfile.mkdtemp())
        self.assertTrue(os.path.exists(os.path.join(top, "install.sh")))

    def test_path_traversal_is_refused(self):
        data = make_archive(GOOD + [("../../evil.sh", b"x")])
        with self.assertRaises(helper.InstallError):
            helper.safe_extract(data, tempfile.mkdtemp())

    def test_absolute_paths_are_refused(self):
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            info = tarfile.TarInfo("/etc/cron.d/evil")
            info.size = 1
            tar.addfile(info, io.BytesIO(b"x"))
        with self.assertRaises(helper.InstallError):
            helper.safe_extract(buf.getvalue(), tempfile.mkdtemp())

    def test_symlinks_are_refused(self):
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            directory = tarfile.TarInfo("top")
            directory.type = tarfile.DIRTYPE
            tar.addfile(directory)
            link = tarfile.TarInfo("top/install.sh")
            link.type = tarfile.SYMTYPE
            link.linkname = "/etc/passwd"
            tar.addfile(link)
        with self.assertRaises(helper.InstallError):
            helper.safe_extract(buf.getvalue(), tempfile.mkdtemp())

    def test_missing_files_are_refused(self):
        for entries in ([("install.sh", b"x")], [("privatetoolbox/__init__.py", b"")]):
            with self.assertRaises(helper.InstallError):
                helper.safe_extract(make_archive(entries), tempfile.mkdtemp())

    def test_download_size_limit(self):
        class Resp:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self, n):
                return b"x" * n
        with mock.patch.object(helper.urllib.request, "urlopen", lambda *a, **k: Resp()):
            with self.assertRaises(helper.InstallError):
                helper.download("https://example.invalid/x", limit=10)


class InstallTests(unittest.TestCase):
    def install(self, runner=None, archive=None, fetch=None):
        runner = runner or Runner()
        fetch = fetch or (lambda url: archive or make_archive(GOOD))
        with mock.patch.object(helper, "installed", return_value=True):
            return helper.install_toolbox(fetch=fetch, runner=runner, workdir=tempfile.mkdtemp()), runner

    def test_downloads_the_pinned_release_only(self):
        seen = []
        self.install(fetch=lambda url: seen.append(url) or make_archive(GOOD))
        self.assertEqual(seen, ["https://github.com/Sorena-max/PrivateToolBox/archive/%s.tar.gz"
                                % helper.TOOLBOX_REF])

    def test_runs_the_installer_from_the_unpacked_files_then_enables_the_bridge(self):
        reply, runner = self.install()
        self.assertTrue(reply["ok"])
        install_call, bridge_call = runner.calls
        self.assertEqual(install_call[0], "bash")
        self.assertTrue(install_call[1].endswith("install.sh"))
        for flag in ("--non-interactive", "--fast", "--local-source"):
            self.assertIn(flag, install_call)
        self.assertEqual(bridge_call, [helper.TOOLBOX_BIN, "integrate", "--yes"])

    def test_commands_are_lists_never_shell_strings(self):
        _, runner = self.install()
        self.assertTrue(all(isinstance(call, list) for call in runner.calls))

    def test_a_failing_installer_stops_before_the_bridge(self):
        reply, runner = self.install(Runner([(1, "boom")]))
        self.assertFalse(reply["ok"])
        self.assertEqual(len(runner.calls), 1)
        self.assertIn("boom", reply["output"])

    def test_a_bad_archive_runs_nothing(self):
        reply, runner = self.install(archive=make_archive(GOOD + [("../../x", b"1")]))
        self.assertFalse(reply["ok"])
        self.assertEqual(runner.calls, [])

    def test_a_network_error_is_reported(self):
        def fetch(url):
            raise OSError("no route")
        reply, runner = self.install(fetch=fetch)
        self.assertFalse(reply["ok"])
        self.assertIn("no route", reply["output"])
        self.assertEqual(runner.calls, [])


class ExecuteTests(unittest.TestCase):
    def test_ping_and_status(self):
        self.assertTrue(helper.execute({"cmd": "ping"})["ok"])
        with mock.patch.object(helper, "installed", return_value=False):
            self.assertEqual(helper.execute({"cmd": "status"})["installed"], False)

    def test_only_two_jobs_exist(self):
        for bad in ({"cmd": "rm"}, {"cmd": None}, {"cmd": "install_toolbox; reboot"}, {}, "x", None, []):
            reply = helper.execute(bad, runner=Runner())
            self.assertFalse(reply["ok"], bad)

    def test_arguments_from_the_bot_are_ignored(self):
        seen = []
        with mock.patch.object(helper, "installed", return_value=True):
            helper.execute({"cmd": "install_toolbox", "ref": "evil", "repo": "evil/evil",
                            "url": "http://evil.invalid/x"},
                           fetch=lambda url: seen.append(url) or make_archive(GOOD), runner=Runner())
        self.assertEqual(len(seen), 1)
        self.assertIn("Sorena-max/PrivateToolBox", seen[0])
        self.assertNotIn("evil", seen[0])

    def test_enable_bridge_needs_the_program(self):
        with mock.patch.object(helper, "installed", return_value=False):
            reply = helper.execute({"cmd": "enable_bridge"}, runner=Runner())
        self.assertFalse(reply["ok"])
        with mock.patch.object(helper, "installed", return_value=True):
            runner = Runner()
            self.assertTrue(helper.execute({"cmd": "enable_bridge"}, runner=runner)["ok"])
        self.assertEqual(runner.calls, [[helper.TOOLBOX_BIN, "integrate", "--yes"]])

    def test_one_job_at_a_time(self):
        helper.LOCK.acquire()
        try:
            self.assertEqual(helper.execute({"cmd": "install_toolbox"}, runner=Runner())["error"], "busy")
        finally:
            helper.LOCK.release()


if __name__ == "__main__":
    unittest.main()
