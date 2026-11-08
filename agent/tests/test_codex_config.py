"""Codex configuration accepts only explicitly selected CLI paths and model IDs."""
from __future__ import annotations

import unittest

from agent import config
from agent.tests.helpers import TempHome


class CodexConfigTest(unittest.TestCase):
    def test_defaults_leave_codex_unconfigured(self):
        summary = config.default_config()["summary"]
        self.assertIsNone(summary["codex_cli_path"])
        self.assertEqual(summary["codex_models"], [])

    def test_codex_settings_roundtrip_without_changing_readiness(self):
        home = TempHome()
        try:
            cfg = config.default_config()
            cfg["summary"]["enabled"] = False
            cfg["summary"]["codex_cli_path"] = "/Applications/Codex/bin/codex"
            cfg["summary"]["codex_models"] = ["local-model-1"]
            config.save(home.paths, cfg)
            saved = config.load(home.paths)
            self.assertEqual(saved["summary"]["codex_cli_path"], cfg["summary"]["codex_cli_path"])
            self.assertEqual(saved["summary"]["codex_models"], ["local-model-1"])
            self.assertFalse(saved["summary"]["enabled"])
        finally:
            home.cleanup()

    def test_rejects_bad_codex_path_and_model_ids(self):
        for key, value in (("codex_cli_path", "relative/codex"),
                           ("codex_models", ["gpt model"]),
                           ("codex_models", ["bad\nmodel"]),
                           ("codex_models", ["same", "same"])):
            cfg = config.default_config()
            cfg["summary"][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(config.ConfigError):
                config.validate_config(cfg)
