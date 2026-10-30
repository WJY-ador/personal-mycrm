"""Exercise the sidecar from the final unpacked desktop bundle, not source."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
from build_agent import ROOT, smoke


def verify(directory):
    package = json.loads((ROOT / "desktop/package.json").read_text(encoding="utf-8"))
    version = package["version"]
    candidates = list(directory.glob("mac*/MyCRM.app/Contents/Resources/agent/build-info.json"))
    candidates += list(directory.glob("win*/resources/agent/build-info.json"))
    if len(candidates) != 1:
        raise ValueError("expected one unpacked desktop and bundled agent")
    info_path = candidates[0]
    info = json.loads(info_path.read_text(encoding="utf-8"))
    allowed = set(json.loads((ROOT / "packaging/agent-files.json").read_text(encoding="utf-8")))
    if set(info["inputs"]) != allowed or info["application_version"] != version or info["agent_protocol"] != 1:
        raise ValueError("bundled source allowlist/version/protocol mismatch")
    binary = info_path.parent / ("mycrm-agent.exe" if sys.platform == "win32" else "mycrm-agent")
    smoke(binary, version)
    extension = ".exe" if sys.platform == "win32" else ".dmg"
    artifacts = [p for p in directory.glob("*" + extension) if version in p.name]
    if not artifacts:
        raise ValueError("native installer missing")
    print("bundle verified: " + ", ".join(p.name for p in artifacts))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path, default=ROOT / "release/desktop", nargs="?")
    verify(parser.parse_args().directory)
