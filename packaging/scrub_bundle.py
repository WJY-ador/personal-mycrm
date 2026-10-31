"""Fail-closed scan of the unpacked desktop bundle (asar contents included) for owner values.

Patterns come only from the CRM_SCRUB_EXTRA environment variable (comma separated), matched like
`crm.py check`: literal, case-insensitive. Pattern values are never printed — only file paths
(with any pattern occurrence masked) and pattern numbers.
"""
from __future__ import annotations
import argparse
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
PATTERN_ENV = "CRM_SCRUB_EXTRA"
ASAR_CLI = ROOT / "desktop/node_modules/@electron/asar/bin/asar.js"


def parse_patterns(raw):
    return [x.strip() for x in (raw or "").split(",") if x.strip()]


def compile_patterns(patterns):
    """Per pattern: (number, byte regexes for UTF-8 and UTF-16LE, text regex for paths)."""
    compiled = []
    for number, value in enumerate(patterns, 1):
        byte_res = [re.compile(re.escape(value.encode(encoding)), re.I) for encoding in ("utf-8", "utf-16-le")]
        compiled.append((number, byte_res, re.compile(re.escape(value), re.I)))
    return compiled


def bundle_roots(directory):
    return sorted(directory.glob("mac*/MyCRM.app")) + sorted(p for p in directory.glob("win*-unpacked") if p.is_dir())


def node_extract(archive, destination):
    subprocess.run(["node", str(ASAR_CLI), "extract", str(archive), str(destination)], check=True)


def mask(text, compiled):
    for _number, _byte_res, text_re in compiled:
        text = text_re.sub("***", text)
    return text


def scan_tree(root, compiled, extract=node_extract, label=""):
    """Return (files scanned, [(masked path, pattern number)]). Symlinks are not followed."""
    scanned, hits = 0, []
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        relative = label + path.relative_to(root).as_posix()
        data = path.read_bytes()
        scanned += 1
        for number, byte_res, text_re in compiled:
            if text_re.search(relative) or any(r.search(data) for r in byte_res):
                hits.append((mask(relative, compiled), number))
        if path.suffix == ".asar":
            with tempfile.TemporaryDirectory() as temp:
                extract(path, Path(temp) / "x")
                inner_scanned, inner_hits = scan_tree(Path(temp) / "x", compiled, extract, relative + "!/")
            scanned += inner_scanned
            hits += inner_hits
    return scanned, hits


def run(directory, raw_patterns, extract=node_extract, out=print):
    patterns = parse_patterns(raw_patterns)
    if not patterns:
        out(PATTERN_ENV + " is empty: refusing to pass the scrub check (fail-closed)")
        return 1
    roots = bundle_roots(directory)
    if not roots:
        out("no unpacked desktop bundle under " + str(directory))
        return 1
    compiled = compile_patterns(patterns)
    total, hits = 0, []
    for root in roots:
        scanned, found = scan_tree(root, compiled, extract, root.relative_to(directory).as_posix() + "/")
        total += scanned
        hits += found
    for path, number in hits:
        out("owner value found: " + path + " (pattern #" + str(number) + ")")
    if hits:
        return 1
    out("scrub ok: " + str(total) + " files, " + str(len(patterns)) + " patterns")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path, default=ROOT / "release/desktop", nargs="?")
    sys.exit(run(parser.parse_args().directory, os.environ.get(PATTERN_ENV, "")))
