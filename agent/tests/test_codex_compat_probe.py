import unittest
import os
import tempfile

from agent.codex_compat_probe import check_observation, digest_package, validate_version


class CompatibilityProbeObservationTest(unittest.TestCase):
    def test_cli_version_must_be_exact_release(self):
        validate_version('codex-cli 0.167.0\n', '0.167.0')
        for actual, expected in [('codex-cli 0.167.1\n', '0.167.0'),
                                 ('codex-cli 0.167.0-rc.1\n', '0.167.0'),
                                 ('codex-cli 0.167.0\n', 'latest')]:
            with self.subTest(actual=actual), self.assertRaises(ValueError):
                validate_version(actual, expected)

    def test_mycrm_tool_must_reach_host_once(self):
        check_observation('read', {'dynamic': ['mycrm_read'], 'outputs': 'synthetic ok',
                                   'requests': 2, 'created': False, 'exposed': False})
        with self.assertRaises(ValueError):
            check_observation('read', {'dynamic': [], 'outputs': 'synthetic ok',
                                        'requests': 2, 'created': False, 'exposed': False})

    def test_blocked_tools_must_fail_and_never_expose_canary(self):
        good = {'dynamic': [], 'outputs': 'Script failed\nScript error: TypeError: tools.read_file is not a function',
                'requests': 2, 'created': False, 'exposed': False}
        check_observation('fileprobe', good)
        for change in ({'exposed': True}, {'created': True}, {'requests': 1},
                       {'outputs': 'success'}, {'dynamic': ['mycrm_read']}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                check_observation('fileprobe', {**good, **change})

    def test_package_digest_detects_runtime_component_changes_and_external_links(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as outside:
            binary = os.path.join(root, 'binary')
            with open(binary, 'wb') as handle:
                handle.write(b'synthetic-1')
            first = digest_package(root)
            with open(binary, 'wb') as handle:
                handle.write(b'synthetic-2')
            self.assertNotEqual(first, digest_package(root))
            os.symlink(outside, os.path.join(root, 'escape'))
            with self.assertRaises(ValueError):
                digest_package(root)
