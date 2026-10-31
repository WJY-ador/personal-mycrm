"""The frozen sidecar must carry its own CA file; the build machine's OpenSSL path is absent for users."""
from pathlib import Path
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packaging"))
CONTRACT = {"app_version": "0.1.1", "agent_version": "0.1.0", "protocol": 1}
# Format-valid only (agent/contract.py TOKEN_RE). Never a real token.
FAKE_TOKEN = "imp_is_000000000000000000000000.fakefake." + "x" * 40


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "packaging" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CaBundleTests(unittest.TestCase):
    def setUp(self):
        self.build = load("build_agent")
        self.temp = tempfile.TemporaryDirectory()
        self.binary = Path(self.temp.name) / "mycrm-agent"
        self.addCleanup(self.temp.cleanup)

    def with_cacert(self):
        target = self.binary.parent / "_internal" / "certifi" / "cacert.pem"
        target.parent.mkdir(parents=True)
        target.write_text("placeholder")

    def test_bundled_ca_passes_and_contract_keys_are_unchanged(self):
        self.with_cacert()
        info = dict(CONTRACT, ca_bundled=True, ca_count=118)
        self.assertEqual(self.build.check_ca(self.binary, info, "0.1.1"), 118)

    def test_sidecar_without_ca_fields_is_rejected(self):
        # The 0.1.1 CI build that failed HTTPS printed only the contract keys.
        self.with_cacert()
        with self.assertRaisesRegex(ValueError, "CA bundle missing"):
            self.build.check_ca(self.binary, dict(CONTRACT), "0.1.1")

    def test_host_ca_or_empty_bundle_is_rejected(self):
        self.with_cacert()
        for bundled, count in [(False, 140), (True, 0), (True, None)]:
            with self.assertRaisesRegex(ValueError, "CA bundle missing"):
                self.build.check_ca(self.binary, dict(CONTRACT, ca_bundled=bundled, ca_count=count), "0.1.1")

    def test_missing_cacert_file_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "file missing"):
            self.build.check_ca(self.binary, dict(CONTRACT, ca_bundled=True, ca_count=1), "0.1.1")

    def test_version_mismatch_is_still_rejected(self):
        self.with_cacert()
        with self.assertRaisesRegex(ValueError, "protocol/version"):
            self.build.check_ca(self.binary, dict(CONTRACT, protocol=2, ca_bundled=True, ca_count=1), "0.1.1")

    def test_smoke_hides_host_ca_paths_from_the_sidecar(self):
        source = (ROOT / "packaging" / "build_agent.py").read_text(encoding="utf-8")
        self.assertIn('env.pop("SSL_CERT_FILE", None)', source)
        self.assertIn('env.pop("SSL_CERT_DIR", None)', source)


class EntryCaTests(unittest.TestCase):
    def setUp(self):
        self.entry = load("agent_entry")

    def test_frozen_entry_sets_bundled_ca_only_when_unset(self):
        fake = mock.Mock(where=lambda: "/bundle/certifi/cacert.pem")
        with mock.patch.object(self.entry, "certifi", fake), mock.patch.object(sys, "frozen", True, create=True):
            with mock.patch.dict(os.environ, {}, clear=True):
                self.entry._use_bundled_ca()
                self.assertEqual(os.environ["SSL_CERT_FILE"], "/bundle/certifi/cacert.pem")
            with mock.patch.dict(os.environ, {"SSL_CERT_FILE": "/corp/ca.pem"}, clear=True):
                self.entry._use_bundled_ca()
                self.assertEqual(os.environ["SSL_CERT_FILE"], "/corp/ca.pem")

    def test_source_runs_keep_system_ca(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.entry._use_bundled_ca()
            self.assertNotIn("SSL_CERT_FILE", os.environ)

    def test_ca_info_survives_a_broken_user_file(self):
        # A closed file, so Windows can reopen it by name.
        with tempfile.TemporaryDirectory() as directory:
            broken = Path(directory) / "broken.pem"
            broken.write_text("not a certificate", encoding="utf-8")
            with mock.patch.dict(os.environ, {"SSL_CERT_FILE": str(broken)}):
                self.assertEqual(self.entry._ca_info(), {"ca_bundled": False, "ca_count": 0})


class ConnectOutputTests(unittest.TestCase):
    def test_connect_failure_output_never_contains_the_stdin_token(self):
        # The desktop shows the last sidecar line on failure. Unreachable local port: no network, no real server.
        with tempfile.TemporaryDirectory() as home:
            env = {k: v for k, v in os.environ.items() if not k.startswith("MYCRM_")}
            env["MYCRM_AGENT_HOME"] = home
            result = subprocess.run(
                [sys.executable, "-m", "agent", "--home", home, "connect", "--server", "https://127.0.0.1:1/",
                 "--token-stdin"], input=FAKE_TOKEN + "\n", cwd=ROOT, env=env, capture_output=True, text=True,
                encoding="utf-8", timeout=60, check=False)
        self.assertNotEqual(result.returncode, 0)
        output = result.stdout + result.stderr
        self.assertIn("서버에 닿지 못했어요", output)  # reached the network step, not the format check
        for secret in (FAKE_TOKEN, FAKE_TOKEN.split(".")[-1], FAKE_TOKEN.split(".")[0]):
            self.assertNotIn(secret, output)


if __name__ == "__main__":
    unittest.main()
