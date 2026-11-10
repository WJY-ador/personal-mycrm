import unittest
import json
import tempfile
from pathlib import Path

from agent.chat_codex_fingerprint import digest_input_hashes, source_fingerprint


class CodexFingerprintTest(unittest.TestCase):
    def test_order_independent_and_changes_for_any_input(self):
        a = {'agent/a.py': 'a' * 64, 'agent/b.py': 'b' * 64}
        b = {'agent/b.py': 'b' * 64, 'agent/a.py': 'a' * 64}
        self.assertEqual(digest_input_hashes(a), digest_input_hashes(b))
        self.assertNotEqual(digest_input_hashes(a), digest_input_hashes({**a, 'agent/b.py': 'c' * 64}))

    def test_rejects_missing_or_malformed_hashes(self):
        for hashes in ({}, {'agent/a.py': 'abc'}, {'../other.py': 'a' * 64}, {'agent/a.py': 'A' * 64}):
            with self.subTest(hashes=hashes), self.assertRaises(ValueError):
                digest_input_hashes(hashes)

    def test_source_fingerprint_tracks_declared_inputs_and_rejects_links(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'agent').mkdir()
            (root / 'packaging').mkdir()
            (root / 'agent/a.py').write_text('safe', encoding='utf-8')
            (root / 'packaging/agent-files.json').write_text(json.dumps(['agent/a.py']), encoding='utf-8')
            first = source_fingerprint(root)
            (root / 'agent/a.py').write_text('changed', encoding='utf-8')
            self.assertNotEqual(first, source_fingerprint(root))
            (root / 'agent/a.py').unlink()
            (root / 'agent/a.py').symlink_to(root / 'packaging/agent-files.json')
            with self.assertRaises(ValueError):
                source_fingerprint(root)
