from pathlib import Path
import importlib.util
import json
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]

def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "packaging" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

class PackagingTests(unittest.TestCase):
    def test_allowlist_does_not_collect_private_worktree_files(self):
        build = load("build_agent")
        with tempfile.TemporaryDirectory(dir=ROOT / "release") as temp:
            hashes = build.stage_source(Path(temp), "0.1.1")
            self.assertEqual(set(hashes), set(json.loads((ROOT / "packaging/agent-files.json").read_text())))
            names = [str(p.relative_to(temp)) for p in Path(temp).rglob("*") if p.is_file()]
            self.assertFalse(any("migration" in p or "notes" in p or "tests" in p or "reconstruction" in p for p in names))
            self.assertNotIn("agent/board_manifest.py", names)
            for relative, digest in hashes.items():
                self.assertEqual(build.sha256(ROOT / relative), digest)

    def test_allowlist_covers_agent_imports(self):
        # 앱 sidecar 가 `migrate login --token-stdin` 을 돌린다 — cli 가 부르는 agent 모듈이 목록에서 빠지면 ImportError
        import ast
        allow = set(json.loads((ROOT / "packaging/agent-files.json").read_text()))
        self.assertIn("agent/migrate.py", allow)
        missing = set()
        for name in sorted(allow):
            tree = ast.parse((ROOT / name).read_text(encoding="utf-8"))
            pkg = Path(name).parent
            for node in ast.walk(tree):
                if not isinstance(node, ast.ImportFrom) or node.level == 0:
                    continue
                base = pkg
                for _ in range(node.level - 1):
                    base = base.parent
                if node.module:
                    targets = [base.joinpath(*node.module.split("."))]
                else:
                    targets = [base / a.name for a in node.names]
                for t in targets:
                    if (ROOT / t).is_dir():
                        t = t / "__init__"
                    rel = str(t.with_suffix(".py")) if not str(t).endswith(".py") else str(t)
                    if (ROOT / rel).exists() and rel not in allow:
                        missing.add(name + " -> " + rel)
        self.assertEqual(missing, set())

    def test_checksum_manifest_is_stable_and_excludes_its_own_output(self):
        checksums = load("checksums")
        with tempfile.TemporaryDirectory(dir=ROOT / "release") as temp:
            directory = Path(temp)
            (directory / "b.exe").write_bytes(b"windows")
            (directory / "a.dmg").write_bytes(b"mac")
            (directory / "private.txt").write_text("not an installer")
            output = checksums.write_checksums(directory)
            first = output.read_text()
            self.assertIn("  a.dmg\n", first)
            self.assertNotIn("private", first)
            self.assertNotIn("SHA256SUMS", first)
            self.assertEqual(checksums.write_checksums(directory).read_text(), first)

if __name__ == "__main__":
    unittest.main()
