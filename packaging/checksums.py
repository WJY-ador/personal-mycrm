"""Sorted SHA256 manifest for installers; writes atomically, excludes itself."""
from __future__ import annotations
import argparse
import hashlib
import os
from pathlib import Path


def write_checksums(directory: Path):
    paths = sorted(p for p in directory.iterdir() if p.is_file() and p.name.endswith((".dmg", ".exe", ".zip", ".blockmap", ".yml")))
    if not paths:
        raise ValueError("no installer artifacts")
    lines = [hashlib.sha256(p.read_bytes()).hexdigest() + "  " + p.name for p in paths]
    output = directory / "SHA256SUMS.txt"
    temp = output.with_suffix(".tmp")
    temp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.replace(temp, output)
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    print(write_checksums(parser.parse_args().directory))
