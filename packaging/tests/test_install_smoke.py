import contextlib
import io
from pathlib import Path
import importlib.util
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packaging"))  # install_smoke imports build_agent like verify_bundle does


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "packaging" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


smoke = load("install_smoke")
WIN_ENV = {"LOCALAPPDATA": r"D:\Profiles\tester\AppData\Local", "APPDATA": r"D:\Profiles\tester\AppData\Roaming",
           "ProgramFiles": r"C:\Program Files", "USERPROFILE": r"D:\Profiles\tester"}


class InstallSmokeTests(unittest.TestCase):
    def test_dispatch_by_platform(self):
        calls = []
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            version = smoke.app_version()
            (directory / ("MyCRM-" + version + "-win-x64.exe")).write_bytes(b"exe")
            (directory / ("MyCRM-" + version + "-mac-arm64.dmg")).write_bytes(b"dmg")
            runners = {"win32": lambda i, v: calls.append(("win", i.name, v)),
                       "darwin": lambda i, v: calls.append(("mac", i.name, v))}
            # Fake installers: keep their progress lines out of the CI log of the real smoke.
            with mock.patch.dict(smoke.RUNNERS, runners, clear=True), contextlib.redirect_stdout(io.StringIO()):
                smoke.main(directory, platform="win32")
                smoke.main(directory, platform="darwin")
                with self.assertRaises(smoke.SmokeError):
                    smoke.main(directory, platform="linux")
        self.assertEqual(calls, [("win", "MyCRM-" + version + "-win-x64.exe", version),
                                 ("mac", "MyCRM-" + version + "-mac-arm64.dmg", version)])

    def test_installer_must_be_unique_for_the_app_version(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            (directory / "MyCRM-0.0.9-win-x64.exe").write_bytes(b"old")
            with self.assertRaises(smoke.SmokeError):
                smoke.installer_for(directory, "win32", "0.1.1")
            (directory / "MyCRM-0.1.1-mac-arm64.dmg").write_bytes(b"a")
            (directory / "MyCRM-0.1.1-mac-x64.dmg").write_bytes(b"b")
            with self.assertRaises(smoke.SmokeError):
                smoke.installer_for(directory, "darwin", "0.1.1")

    def test_uninstall_command_prefers_quiet_string_and_parses_quoted_path(self):
        exe = r"D:\Profiles\tester\AppData\Local\Programs\mycrm-desktop\Uninstall MyCRM.exe"
        values = {"UninstallString": '"' + exe + '" /currentuser',
                  "QuietUninstallString": '"' + exe + '" /currentuser /S'}
        self.assertEqual(smoke.uninstall_command(values), values["QuietUninstallString"])
        self.assertEqual(smoke.uninstall_command({"UninstallString": values["UninstallString"]}),
                         values["UninstallString"] + " /S")
        self.assertEqual(smoke.quoted_executable(values["QuietUninstallString"]), exe)
        with self.assertRaises(smoke.SmokeError):
            smoke.quoted_executable(exe + " /S")
        with self.assertRaises(smoke.SmokeError):
            smoke.uninstall_command({})

    def test_product_entry_matches_display_name_and_version(self):
        entries = [("other", {"DisplayName": "Git"}), ("guid", {"DisplayName": "MyCRM 0.1.1"})]
        self.assertEqual(smoke.product_entry(entries, "0.1.1")[0], "guid")
        self.assertIsNone(smoke.product_entry(entries, "0.1.2"))
        with self.assertRaises(smoke.SmokeError):
            smoke.product_entry(entries + [("dup", {"DisplayName": "MyCRM 0.1.1"})], "0.1.1")

    def test_location_kind(self):
        self.assertEqual(smoke.location_kind(r"D:\Profiles\tester\AppData\Local\Programs\mycrm-desktop", WIN_ENV),
                         "per-user (%LOCALAPPDATA%\\Programs)")
        self.assertEqual(smoke.location_kind(r"d:\PROFILES\tester\appdata\local\programs\x", WIN_ENV),
                         "per-user (%LOCALAPPDATA%\\Programs)")
        self.assertEqual(smoke.location_kind(r"C:\Program Files\MyCRM", WIN_ENV), "per-machine (%ProgramFiles%)")
        self.assertEqual(smoke.location_kind(r"D:\Profiles\tester\AppData\Local\ProgramsX\a", WIN_ENV), "other")
        self.assertEqual(smoke.location_kind(r"D:\MyCRM", {}), "other")

    def test_redact_hides_user_and_temp_paths(self):
        env = dict(WIN_ENV, TMPDIR="/var/folders/ab/T/")
        text = (r"failed at d:\profiles\tester\appdata\local\Programs\x and D:\Profiles\tester\AppData\Roaming\my-crm-agent"
                " and /private/var/folders/ab/T/install-smoke-1/app and /work/repo/release")
        out = smoke.redact(text, env, extra=[("repo", "/work/repo")])
        self.assertNotIn("tester", out.lower())
        self.assertNotIn("/var/folders", out)
        self.assertNotIn("/work/repo", out)
        self.assertIn(r"%LOCALAPPDATA%\Programs\x", out)
        self.assertIn(r"%APPDATA%\my-crm-agent", out)
        self.assertIn("<repo>/release", out)


if __name__ == "__main__":
    unittest.main()
