from pathlib import Path
import importlib.util
import shutil
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "packaging" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


scrub = load("scrub_bundle")
SECRET = "Fake-Owner-Zq7"


class ScrubBundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.dist = Path(self.temp.name)
        self.app = self.dist / "mac-arm64/MyCRM.app/Contents"
        (self.app / "Resources").mkdir(parents=True)
        (self.app / "Info.plist").write_text("<plist>MyCRM</plist>")
        asar = self.app / "Resources/app.asar"
        asar.write_bytes(b"opaque archive bytes")
        self.asar_source = self.dist / "asar-source"  # outside the bundle roots
        self.asar_source.mkdir()
        (self.asar_source / "main.cjs").write_text("console.log('clean')")
        self.extracted = []
        self.lines = []

    def fake_extract(self, archive, destination):
        """Stand-in for @electron/asar extract."""
        self.extracted.append(archive.name)
        shutil.copytree(self.asar_source, destination)

    def tearDown(self):
        self.temp.cleanup()

    def run_scrub(self, patterns=SECRET + ", other-fake "):
        return scrub.run(self.dist, patterns, self.fake_extract, self.lines.append)

    def output(self):
        return "\n".join(self.lines)

    def test_empty_secret_fails_closed(self):
        for raw in ("", " , ,", None):
            self.assertEqual(scrub.run(self.dist, raw, self.fake_extract, self.lines.append), 1)
        self.assertIn("fail-closed", self.output())

    def test_missing_bundle_fails(self):
        shutil.rmtree(self.dist / "mac-arm64")
        self.assertEqual(self.run_scrub(), 1)

    def test_clean_bundle_passes_and_counts_asar_contents(self):
        self.assertEqual(self.run_scrub(), 0)
        self.assertIn("scrub ok: 3 files, 2 patterns", self.output())
        self.assertEqual(self.extracted, ["app.asar"])

    def test_value_inside_asar_is_found_case_insensitively_without_printing_it(self):
        (self.asar_source / "main.cjs").write_text("const who='" + SECRET.upper() + "'")
        self.assertEqual(self.run_scrub(), 1)
        self.assertIn("mac-arm64/MyCRM.app/Contents/Resources/app.asar!/main.cjs (pattern #1)", self.output())
        self.assertNotIn(SECRET.lower(), self.output().lower())

    def test_utf16_value_in_binary_and_value_in_file_name_are_found_and_masked(self):
        (self.app / "Resources/version.rc").write_bytes(b"\x00\x01" + SECRET.encode("utf-16-le"))
        (self.app / ("notes-" + SECRET + ".txt")).write_text("plain")
        self.assertEqual(self.run_scrub(), 1)
        self.assertIn("Resources/version.rc (pattern #1)", self.output())
        self.assertIn("notes-***.txt (pattern #1)", self.output())
        self.assertNotIn(SECRET.lower(), self.output().lower())

    def test_windows_unpacked_bundle_is_scanned(self):
        shutil.rmtree(self.dist / "mac-arm64")
        win = self.dist / "win-unpacked/resources"
        win.mkdir(parents=True)
        (win / "agent.txt").write_text("x other-FAKE y")
        self.assertEqual(self.run_scrub(), 1)
        self.assertIn("win-unpacked/resources/agent.txt (pattern #2)", self.output())

    def test_symlinks_are_not_followed(self):
        outside = self.dist / "outside.txt"
        outside.write_text(SECRET)
        try:
            (self.app / "link.txt").symlink_to(outside)
        except OSError:
            self.skipTest("symlinks unavailable on this runner")
        self.assertEqual(self.run_scrub(), 0)


if __name__ == "__main__":
    unittest.main()
