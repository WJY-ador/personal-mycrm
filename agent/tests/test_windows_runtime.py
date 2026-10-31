"""Windows native boundary tests use memory APIs and fake schtasks; no OS changes."""
from __future__ import annotations

import ctypes
import contextlib
import io
import os
import plistlib
import subprocess
import sys
import unittest
import xml.etree.ElementTree as ET
from unittest import mock

from agent import cli, config, keystore, osutil, schedule
from agent.tests.helpers import TempHome, TOKEN, run_cli


@contextlib.contextmanager
def temp_home():
    home = TempHome()
    try:
        yield home
    finally:
        home.cleanup()


class MemoryCredentials:
    def __init__(self):
        self.values = {}

    def read(self, target):
        return self.values.get(target)

    def write(self, target, account, secret):
        self.values[target] = secret

    def delete(self, target):
        return self.values.pop(target, None) is not None


class WindowsCredentialsTest(unittest.TestCase):
    def test_roundtrip_isolated_accounts(self):
        api = MemoryCredentials()
        first = keystore.WindowsCredentialStore("first", api=api)
        second = keystore.WindowsCredentialStore("second", api=api)
        self.assertIsNone(first.get("upload:x"))
        first.set("upload:x", TOKEN)
        second.set("upload:x", "b" * 32)
        self.assertEqual(first.get("upload:x"), TOKEN)
        self.assertEqual(second.get("upload:x"), "b" * 32)
        self.assertTrue(first.delete("upload:x"))
        self.assertFalse(first.delete("upload:x"))
        self.assertEqual(second.get("upload:x"), "b" * 32)

    def test_invalid_input_and_failed_verification(self):
        api = MemoryCredentials()
        store = keystore.WindowsCredentialStore("my-crm-agent", api=api)
        for value in ('a"; command', "", None):
            with self.assertRaises(keystore.KeyStoreError):
                store.get(value)
        for value in ("short", 'x"' * 32, None):
            with self.assertRaises(keystore.KeyStoreError):
                store.set("a", value)
        self.assertFalse(api.values)
        with mock.patch.object(api, "read", return_value=None):
            with self.assertRaisesRegex(keystore.KeyStoreError, "not readable"):
                store.set("a", TOKEN)

    def test_native_blob_size_free_and_no_subprocess(self):
        class Fn:
            def __init__(self, fn):
                self.fn = fn
            def __call__(self, *args):
                return self.fn(*args)
        values, freed, blobs = {}, [], []
        dll = type("DLL", (), {})()
        api = None
        references = []
        def write(ptr, flags):
            entry = ctypes.cast(ptr, ctypes.POINTER(api.Credential)).contents
            values[entry.TargetName] = ctypes.string_at(entry.CredentialBlob, entry.CredentialBlobSize)
            blobs.append((entry.CredentialBlob, entry.CredentialBlobSize))
            self.assertEqual(entry.Type, 1)
            self.assertEqual(entry.Persist, 2)
            self.assertEqual(flags, 0)
            return True
        def read(target, typ, flags, output):
            self.assertEqual(typ, 1)
            raw = values.get(target)
            if raw is None:
                return False
            blob = ctypes.create_string_buffer(raw)
            entry = api.Credential()
            entry.CredentialBlob = ctypes.cast(blob, ctypes.c_void_p)
            entry.CredentialBlobSize = len(raw)
            references.extend((blob, entry))
            ctypes.cast(output, ctypes.POINTER(ctypes.POINTER(api.Credential)))[0] = ctypes.pointer(entry)
            return True
        dll.CredWriteW = Fn(write)
        dll.CredReadW = Fn(read)
        dll.CredDeleteW = Fn(lambda target, typ, flags: values.pop(target, None) is not None)
        dll.CredFree = Fn(lambda pointer: freed.append(pointer))
        with mock.patch.object(osutil, "IS_WINDOWS", True), \
             mock.patch.object(ctypes, "WinDLL", return_value=dll, create=True), \
             mock.patch.object(ctypes, "get_last_error", return_value=1168, create=True), \
             mock.patch("subprocess.run", side_effect=AssertionError("no subprocess")):
            api = keystore._WindowsCredentialAPI()
            store = keystore.WindowsCredentialStore("test", api=api)
            store.set("token", TOKEN)
            self.assertEqual(store.get("token"), TOKEN)
            self.assertEqual(values["test:token"], TOKEN.encode("utf-8"))
            self.assertEqual(len(freed), 2)
            self.assertTrue(store.delete("token"))
            self.assertFalse(store.delete("token"))
            self.assertIsNone(store.get("token"))
            with mock.patch.object(ctypes, "get_last_error", return_value=5, create=True):
                with self.assertRaisesRegex(keystore.KeyStoreError, "Windows error 5") as err:
                    store.get("token")
                self.assertNotIn(TOKEN, str(err.exception))


class ScheduleRuntimeTest(unittest.TestCase):
    def test_frozen_macos_no_module_flag(self):
        blob = schedule.build_plist(python="/Applications/MyCRM/agent", home="/tmp/my crm",
                                    workdir="/Applications/MyCRM", frozen=True)
        args = plistlib.loads(blob)["ProgramArguments"]
        self.assertEqual(args, ["/Applications/MyCRM/agent", "--home", "/tmp/my crm", "run-once", "--scheduled"])

    def test_windows_xml_quoting_hourly_and_current_user_only(self):
        blob = schedule.build_task_xml(python=r"C:\Program Files\MyCRM\agent.exe",
                                      home=r"C:\ProgramData\My CRM & data",
                                      workdir=r"C:\Program Files\MyCRM", user=r"DOMAIN\User", frozen=True)
        root = ET.fromstring(blob)
        ns = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
        text = lambda key: root.find(".//t:" + key, ns).text
        self.assertEqual(text("Interval"), "PT1H")
        self.assertEqual(text("LogonType"), "InteractiveToken")
        self.assertEqual(text("RunLevel"), "LeastPrivilege")
        self.assertEqual(text("MultipleInstancesPolicy"), "IgnoreNew")
        self.assertEqual(text("Command"), r"C:\Program Files\MyCRM\agent.exe")
        self.assertIn('"C:\\ProgramData\\My CRM & data"', text("Arguments"))
        self.assertNotIn("-m agent", text("Arguments"))
        self.assertNotIn(TOKEN.encode(), blob)
        self.assertNotIn("Password", blob.decode("utf-16"))

    def test_windows_scheduler_retry_and_remove(self):
        with temp_home() as home:
            state = {"exists": False, "failure": False}
            calls = []
            def fake(argv):
                calls.append(argv)
                if "/Query" in argv:
                    return subprocess.CompletedProcess(argv, 0 if state["exists"] else 1, "", "")
                if state["failure"]:
                    return subprocess.CompletedProcess(argv, 5, "", "")
                state["exists"] = "/Create" in argv
                return subprocess.CompletedProcess(argv, 0, "", "")
            with mock.patch.object(osutil, "IS_WINDOWS", True), \
                 mock.patch.object(osutil, "IS_MAC", False), \
                 mock.patch.object(schedule, "build_task_xml", return_value=b"task XML"):
                self.assertFalse(schedule.installed(runner=fake))
                state["failure"] = True
                with self.assertRaises(schedule.ScheduleError):
                    schedule.install(home=home.home, runner=fake)
                self.assertFalse(os.path.exists(os.path.join(home.home, "schedule", "agent-task.xml")))
                state["failure"] = False
                self.assertEqual(schedule.install(home=home.home, runner=fake), "installed")
                self.assertTrue(schedule.installed(runner=fake))
                self.assertEqual(schedule.install(home=home.home, runner=fake), "unchanged")
                state["exists"] = False
                self.assertEqual(schedule.install(home=home.home, runner=fake), "installed")
                self.assertEqual(schedule.remove(runner=fake), "removed")
                self.assertEqual(schedule.remove(runner=fake), "absent")
                self.assertTrue(os.path.isdir(home.paths.raw))
            self.assertNotIn(TOKEN, str(calls))


class ConfigureCliTest(unittest.TestCase):
    def test_setting_and_clearing_preserve_other_configuration(self):
        with temp_home() as home:
            cfg = config.load(home.paths)
            cfg["device_label"] = "keep me"
            cfg["summary"]["enabled"] = False
            config.save(home.paths, cfg)
            binary = os.path.join(home.root, "fake claude.exe" if osutil.IS_WINDOWS else "fake claude")
            with open(binary, "w") as stream:
                stream.write("fake executable, never invoked")
            os.chmod(binary, 0o700)
            def call(*args):
                return run_cli(["--home", home.home, "configure-cli"] + list(args))
            code, out = call("--path", binary)
            self.assertEqual(code, 0, out)
            current = config.load(home.paths)
            self.assertEqual(current["summary"]["cli_path"], os.path.realpath(binary))
            self.assertFalse(current["summary"]["enabled"])
            self.assertEqual(current["device_label"], "keep me")
            self.assertNotIn(binary, out)
            with open(home.paths.config, "rb") as fh:
                before = fh.read()
            for path in ("relative", os.path.join(home.root, "absent"), home.root):
                self.assertEqual(call("--path", path)[0], 1)
                with open(home.paths.config, "rb") as fh:
                    self.assertEqual(fh.read(), before)
            self.assertEqual(call("--clear")[0], 0)
            self.assertIsNone(config.load(home.paths)["summary"]["cli_path"])
            self.assertEqual(config.load(home.paths)["device_label"], "keep me")


class Utf8OutputTest(unittest.TestCase):
    def test_cp1252_pipe_prints_korean_help(self):
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        env = dict(os.environ, PYTHONIOENCODING="cp1252")
        env.pop("PYTHONUTF8", None)
        proc = subprocess.run([sys.executable, "-m", "agent", "--help"], cwd=root, env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr.decode("utf-8", "replace"))
        out = proc.stdout.decode("utf-8")
        self.assertTrue(any("\uac00" <= ch <= "\ud7a3" for ch in out), out)


if __name__ == "__main__":
    unittest.main()
