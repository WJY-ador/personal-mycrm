"""Synthetic tests for the explicit Codex CLI/model setup command."""
from __future__ import annotations

import os
import json
import shutil
import stat
import sys
import tempfile
import types
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from agent import config
from agent.tests.helpers import TempHome, run_cli


class ConfigureCodexTest(unittest.TestCase):
    def setUp(self):
        self.home = TempHome()
        self.addCleanup(self.home.cleanup)
        config.save(self.home.paths, config.default_config())
        self.cli = os.path.join(self.home.root, "codex-fixture")
        with open(self.cli, "w", encoding="utf-8") as handle:
            handle.write("synthetic executable; never invoked")
        os.chmod(self.cli, 0o700)

    def call(self, *args):
        return run_cli(["--home", self.home.home, "configure-codex", *args])

    def config_bytes(self):
        with open(self.home.paths.config, "rb") as handle:
            return handle.read()

    def test_version_status_reports_managed_cli_without_exposing_path_or_secrets(self):
        self.call('--path', self.cli, '--model', 'synthetic')
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'synthetic-secret'}), \
             patch('agent.chat_codex_update.inspect_managed_cli', return_value={'path':self.cli, 'version':'0.168.0'}), \
             patch('agent.chat_codex_app_provider._capture_version_output', return_value='codex-cli 0.168.0\n') as run:
            code, output = run_cli(['--home', self.home.home, 'codex-version-status'])
        self.assertEqual(code, 0, output)
        result = json.loads(output)
        self.assertEqual(result['status'], 'supported')
        self.assertEqual(result['installed_version'], '0.168.0')
        self.assertNotIn(self.cli, output)
        self.assertNotIn('synthetic-secret', output)
        self.assertNotIn('OPENAI_API_KEY', run.call_args.kwargs['env'])

    def test_version_status_without_policy_reports_unavailable_policy_not_missing_cli(self):
        with patch('agent.chat_codex_update.inspect_managed_cli', side_effect=ValueError('compatibility-policy-unavailable')):
            code, output = run_cli(['--home', self.home.home, 'codex-version-status'])
        self.assertEqual(code, 0, output)
        result = json.loads(output)
        self.assertEqual(result['status'], 'policy_unavailable')
        self.assertEqual(result['recommended_action'], 'retry')

    def test_version_status_reports_unready_trust_without_claiming_cli_is_missing(self):
        with patch('agent.chat_codex_update.inspect_managed_cli', side_effect=ValueError('managed-codex-not-ready')):
            code, output = run_cli(['--home', self.home.home, 'codex-version-status'])
        self.assertEqual(code, 0, output)
        self.assertEqual(json.loads(output)['status'], 'policy_unverified')
        self.assertNotIn('managed-codex-not-ready', output)

    def test_version_status_explains_expired_policy(self):
        with patch('agent.chat_codex_update.inspect_managed_cli', side_effect=ValueError('compatibility-policy-expired')):
            code, output = run_cli(['--home', self.home.home, 'codex-version-status'])
        self.assertEqual(code, 0, output)
        result = json.loads(output)
        self.assertEqual(result['status'], 'policy_expired')
        self.assertEqual(result['recommended_action'], 'update_mycrm')

    def test_version_status_explains_managed_setup_required(self):
        with patch('agent.chat_codex_update.inspect_managed_cli', side_effect=ValueError('managed-cli-setup-required')):
            code, output = run_cli(['--home', self.home.home, 'codex-version-status'])
        self.assertEqual(code, 0, output)
        result = json.loads(output)
        self.assertEqual(result['status'], 'setup_required')
        self.assertEqual(result['recommended_action'], 'start_login')

    def test_saves_real_cli_path_and_repeated_explicit_model_ids(self):
        cfg = config.load(self.home.paths)
        cfg["device_label"] = "keep synthetic setting"
        cfg["summary"]["enabled"] = False
        config.save(self.home.paths, cfg)
        code, output = self.call("--path", self.cli, "--model", "gpt-6.1-sol", "--model", "codex-team/model_v2")
        self.assertEqual(code, 0, output)
        saved = config.load(self.home.paths)
        self.assertEqual(saved["summary"]["codex_cli_path"], os.path.realpath(self.cli))
        self.assertEqual(saved["summary"]["codex_models"], ["gpt-6.1-sol", "codex-team/model_v2"])
        self.assertFalse(saved["summary"]["enabled"])
        self.assertEqual(saved["device_label"], "keep synthetic setting")
        self.assertNotIn(self.cli, output)

    def test_rejects_invalid_cli_paths_without_mutating_config(self):
        before = self.config_bytes()
        invalid_paths = ("relative/codex", os.path.join(self.home.root, "missing"), self.home.root)
        for path in invalid_paths:
            with self.subTest(path=path):
                code, _output = self.call("--path", path, "--model", "gpt-6.1-sol")
                self.assertEqual(code, 1)
                with open(self.home.paths.config, "rb") as handle:
                    self.assertEqual(handle.read(), before)

    def test_rejects_invalid_or_duplicate_models_without_mutating_config(self):
        before = self.config_bytes()
        bad_model_sets = (("bad model",), ("bad\nmodel",), ("same", "same"), tuple(f"m{i}" for i in range(21)))
        for models in bad_model_sets:
            with self.subTest(models=models):
                args = ["--path", self.cli]
                for model in models:
                    args.extend(("--model", model))
                code, _output = self.call(*args)
                self.assertEqual(code, 1)
                with open(self.home.paths.config, "rb") as handle:
                    self.assertEqual(handle.read(), before)


@unittest.skipUnless(os.name == "posix" and hasattr(os, "O_NOFOLLOW"), "private POSIX storage required")
class CodexVersionStatusFreshHomeTest(unittest.TestCase):
    """Real inspect_managed_cli on a home that does not exist yet (fresh install)."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="mcrm-version-status-")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.home = os.path.join(self.root, "home")

    def status(self, *, keys, system="Darwin"):
        build = types.ModuleType("_desktop_build")
        build.APP_VERSION = "0.1.2"
        build.CODEX_CONFIG_SHA256 = "b" * 64
        with patch("agent.chat_codex_update.TRUSTED_COMPAT_KEYS", keys), \
             patch("agent.chat_codex_update.platform.system", return_value=system), \
             patch("agent.chat_codex_update.platform.machine", return_value="arm64"), \
             patch.dict(sys.modules, {"_desktop_build": build}):
            code, output = run_cli(["--home", self.home, "codex-version-status"])
        self.assertEqual(code, 0, output)
        return json.loads(output)

    def test_fresh_home_without_pinned_keys_reports_unverified_and_creates_nothing(self):
        result = self.status(keys={})
        self.assertEqual(result["status"], "policy_unverified")
        self.assertEqual(result["recommended_action"], "update_mycrm")
        self.assertIsNone(result["installed_version"])
        self.assertEqual(result["supported_versions"], [])
        self.assertFalse(os.path.lexists(self.home))

    def test_fresh_home_with_ready_build_reports_setup_required_and_creates_nothing(self):
        result = self.status(keys={"synthetic": object()})
        self.assertEqual(result["status"], "setup_required")
        self.assertEqual(result["recommended_action"], "start_login")
        self.assertFalse(os.path.lexists(self.home))

    def test_non_mac_reports_unverified_before_any_storage_check(self):
        result = self.status(keys={"synthetic": object()}, system="Windows")
        self.assertEqual(result["status"], "policy_unverified")
        self.assertFalse(os.path.lexists(self.home))

    def test_existing_non_private_home_still_fails_closed(self):
        os.mkdir(self.home)
        os.chmod(self.home, 0o755)
        result = self.status(keys={"synthetic": object()})
        self.assertEqual(result["status"], "policy_unavailable")
        self.assertEqual(stat.S_IMODE(os.stat(self.home).st_mode), 0o755)

    def test_prepare_managed_creates_private_home_before_resolving(self):
        seen = {}
        def resolve(home, _store):
            seen["mode"] = stat.S_IMODE(os.stat(home).st_mode)
            return {"path": "/synthetic-managed/codex", "version": "0.168.0"}
        with patch("agent.chat_codex_update.resolve_managed_cli", side_effect=resolve):
            code, output = run_cli(["--home", self.home, "codex-prepare-managed"])
        self.assertEqual(code, 0, output)
        self.assertEqual(seen.get("mode"), 0o700)
        self.assertEqual(json.loads(output), {"path": "/synthetic-managed/codex", "version": "0.168.0"})


if __name__ == "__main__":
    unittest.main()
