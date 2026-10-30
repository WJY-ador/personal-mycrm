"""Build a native sidecar from an explicit source allowlist, never the worktree."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
PACKAGING = ROOT / "packaging"


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stage_source(destination, version, root=ROOT):
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?", version):
        raise ValueError("invalid application version")
    allowlist = json.loads((PACKAGING / "agent-files.json").read_text(encoding="utf-8"))
    if len(allowlist) != len(set(allowlist)):
        raise ValueError("duplicate package input")
    hashes = {}
    for name in allowlist:
        source = root / name
        if not name.startswith("agent/") or ".." in Path(name).parts or source.is_symlink():
            raise ValueError("unsafe package input")
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
        hashes[name] = sha256(target)
    shutil.copyfile(PACKAGING / "agent_entry.py", destination / "agent_entry.py")
    (destination / "_desktop_build.py").write_text("APP_VERSION = " + repr(version) + "\n", encoding="utf-8")
    return hashes


def smoke(binary, version):
    with tempfile.TemporaryDirectory(prefix="agent-smoke-", dir=ROOT / "release") as scratch:
        home = Path(scratch) / "isolated-home"
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        env.pop("PYTHONHOME", None)
        env.pop("MYCRM_DESKTOP_CONTROL", None)
        env["MYCRM_AGENT_HOME"] = str(home)
        info = subprocess.run([str(binary), "--desktop-info"], cwd=scratch, env=env, check=True,
                              capture_output=True, text=True, timeout=30)
        if json.loads(info.stdout) != {"app_version": version, "agent_version": "0.1.0", "protocol": 1}:
            raise ValueError("unexpected sidecar protocol/version")
        subprocess.run([str(binary), "--help"], cwd=scratch, env=env, check=True,
                       capture_output=True, timeout=30)
        subprocess.run([str(binary), "--home", str(home), "status"], cwd=scratch, env=env,
                       check=True, capture_output=True, timeout=30)


def build(output, version):
    package = json.loads((ROOT / "desktop" / "package.json").read_text(encoding="utf-8"))
    if package["version"] != version:
        raise ValueError("desktop and sidecar application versions differ")
    release = ROOT / "release"
    release.mkdir(exist_ok=True)
    output = output.resolve()
    if output != release / "agent":
        raise ValueError("output must be this project's release/agent directory")
    with tempfile.TemporaryDirectory(prefix="agent-build-", dir=release) as temp:
        scratch = Path(temp)
        stage = scratch / "source"
        stage.mkdir()
        hashes = stage_source(stage, version)
        cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir",
               "--name", "mycrm-agent", "--distpath", str(scratch / "dist"),
               "--workpath", str(scratch / "work"), "--specpath", str(scratch),
               "--paths", str(stage), str(stage / "agent_entry.py")]
        build_env = dict(os.environ)
        build_env["PYINSTALLER_CONFIG_DIR"] = str(release / ".pyinstaller-cache")
        subprocess.run(cmd, cwd=stage, env=build_env, check=True)
        built = scratch / "dist" / "mycrm-agent"
        binary = built / ("mycrm-agent.exe" if sys.platform == "win32" else "mycrm-agent")
        smoke(binary, version)
        if any(sha256(ROOT / name) != digest for name, digest in hashes.items()):
            raise ValueError("source changed during build; rebuild the sidecar")
        (built / "build-info.json").write_text(json.dumps({
            "application_version": version, "agent_protocol": 1, "agent_version": "0.1.0",
            "platform": sys.platform, "architecture": platform.machine(), "inputs": hashes,
        }, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        backup = release / ".agent-previous"
        if backup.exists():
            raise ValueError("previous sidecar recovery directory exists; inspect it before building")
        if output.exists():
            output.rename(backup)
        try:
            built.rename(output)
        except OSError:
            if backup.exists():
                backup.rename(output)
            raise
        if backup.exists():
            shutil.rmtree(backup)
    print(str(output))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "release" / "agent")
    parser.add_argument("--app-version", default="0.1.1")
    args = parser.parse_args()
    build(args.output, args.app_version)
