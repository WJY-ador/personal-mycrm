"""Install, run and remove the built installer the way a user would, on a clean CI runner.

Windows: silent per-user NSIS install, installed sidecar contract, silent uninstall that keeps user data.
macOS: mount the DMG, copy the app into a scratch Applications folder, verify signature and sidecar,
launch the app with an isolated home for a few seconds.

Output names kinds and file names only. Local paths are redacted, even in failures.
"""
from __future__ import annotations

import argparse
import json
import ntpath
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import time

from build_agent import ROOT, smoke

PRODUCT = "MyCRM"
# Agent home (desktop/src/policy.cjs agentHome) and Electron userData (package.json name).
# nsis deleteAppDataOnUninstall would remove $APPDATA\<package name>; neither folder may disappear.
USER_DATA_DIRS = ("my-crm-agent", "mycrm-desktop")
MARKER = "keep.txt"
UNINSTALL_ROOT = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
LAUNCH_SECONDS = 5
REDACT_VARS = ("LOCALAPPDATA", "APPDATA", "TEMP", "TMP", "TMPDIR", "USERPROFILE", "HOME",
               "RUNNER_TEMP", "GITHUB_WORKSPACE")


class SmokeError(Exception):
    pass


def app_version():
    return json.loads((ROOT / "desktop/package.json").read_text(encoding="utf-8"))["version"]


def installer_for(directory, platform, version):
    extension = ".exe" if platform == "win32" else ".dmg"
    matches = sorted(directory.glob(PRODUCT + "-" + version + "-*" + extension))
    if len(matches) != 1:
        raise SmokeError("expected one " + extension + " installer for " + version + ", found " + str(len(matches)))
    return matches[0]


def redact(text, env=None, extra=()):
    env = os.environ if env is None else env
    pairs = [(value, "%" + name + "%") for name in REDACT_VARS if (value := env.get(name))]
    pairs += [(str(value), "<" + label + ">") for label, value in extra]
    for value, label in sorted(pairs, key=lambda pair: len(pair[0]), reverse=True):
        if len(value) > 3:
            text = re.sub(re.escape(value), lambda _m, label=label: label, text, flags=re.IGNORECASE)
    return text


def quoted_executable(command):
    match = re.match(r'\s*"([^"]+)"', command or "")
    if not match:
        raise SmokeError("uninstall command does not start with a quoted executable")
    return match.group(1)


def uninstall_command(values):
    if values.get("QuietUninstallString"):
        return values["QuietUninstallString"]
    if values.get("UninstallString"):
        return values["UninstallString"] + " /S"
    raise SmokeError("uninstall entry has no uninstall command")


def location_kind(path, env=None):
    env = os.environ if env is None else env
    target = ntpath.normcase(ntpath.normpath(str(path)))
    bases = [("per-user (%LOCALAPPDATA%\\Programs)", env.get("LOCALAPPDATA") and ntpath.join(env["LOCALAPPDATA"], "Programs")),
             ("per-machine (%ProgramFiles%)", env.get("ProgramFiles")),
             ("per-machine (%ProgramFiles(x86)%)", env.get("ProgramFiles(x86)"))]
    for label, base in bases:
        if base and target.startswith(ntpath.normcase(ntpath.normpath(base)) + "\\"):
            return label
    return "other"


def wait_until(condition, seconds, interval=1.0):
    deadline = time.monotonic() + seconds
    while True:
        value = condition()
        if value or time.monotonic() >= deadline:
            return value
        time.sleep(interval)


# ---------------------------------------------------------------- Windows

def uninstall_entries(winreg):
    entries = []
    try:
        root = winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL_ROOT)
    except OSError:
        return entries
    with root:
        index = 0
        while True:
            try:
                name = winreg.EnumKey(root, index)
            except OSError:
                break
            index += 1
            values = {}
            try:
                with winreg.OpenKey(root, name) as key:
                    for field in ("DisplayName", "DisplayVersion", "UninstallString", "QuietUninstallString"):
                        try:
                            values[field] = str(winreg.QueryValueEx(key, field)[0])
                        except OSError:
                            pass
            except OSError:
                continue
            entries.append((name, values))
    return entries


def product_entry(entries, version):
    found = [(name, values) for name, values in entries if values.get("DisplayName") == PRODUCT + " " + version]
    if len(found) > 1:
        raise SmokeError("more than one per-user uninstall entry for " + PRODUCT)
    return found[0] if found else None


def windows(installer, version):
    import winreg
    appdata = Path(os.environ["APPDATA"])
    markers = {}
    for name in USER_DATA_DIRS:
        marker = appdata / name / MARKER
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("install-smoke " + name + "\n", encoding="utf-8")
        markers[marker] = marker.read_bytes()
    state = {"installer_exit": None, "uninstaller_exit": None, "entry_found": False,
             "install_kind": None, "install_dir_exists": None, "entry_after_uninstall": None}
    try:
        state["installer_exit"] = subprocess.run([str(installer), "/S", "/currentuser"], timeout=600).returncode
        if state["installer_exit"] != 0:
            raise SmokeError("silent installer exited " + str(state["installer_exit"]))
        entry = wait_until(lambda: product_entry(uninstall_entries(winreg), version), 60)
        if not entry:
            raise SmokeError("no per-user uninstall entry named '" + PRODUCT + " " + version + "'")
        state["entry_found"] = True
        command = uninstall_command(entry[1])
        install_dir = Path(quoted_executable(command)).parent
        state["install_kind"] = location_kind(install_dir)
        state["install_dir_exists"] = install_dir.is_dir()
        print("installed: " + entry[1]["DisplayName"] + " at " + state["install_kind"])
        if not state["install_kind"].startswith("per-user"):
            raise SmokeError("installer did not use the per-user location")
        if not (install_dir / (PRODUCT + ".exe")).is_file():
            raise SmokeError("installed app executable missing")
        smoke(install_dir / "resources" / "agent" / "mycrm-agent.exe", version)
        print("installed sidecar: --desktop-info contract matches, --help and status exit 0")

        state["uninstaller_exit"] = subprocess.run(command, timeout=300).returncode
        if state["uninstaller_exit"] != 0:
            raise SmokeError("silent uninstaller exited " + str(state["uninstaller_exit"]))
        # The NSIS uninstaller re-launches itself from a temp copy and returns at once; wait for the effect.
        removed = wait_until(lambda: not install_dir.exists() and product_entry(uninstall_entries(winreg), version) is None, 180)
        state["install_dir_exists"] = install_dir.exists()
        state["entry_after_uninstall"] = product_entry(uninstall_entries(winreg), version) is not None
        if not removed:
            raise SmokeError("uninstall did not remove the install folder and uninstall entry")
        print("uninstalled: install folder removed, uninstall entry removed")
        for marker, content in markers.items():
            if not marker.is_file() or marker.read_bytes() != content:
                raise SmokeError("user data removed by uninstall: %APPDATA%\\" + marker.parent.name + "\\" + MARKER)
            print("user data kept: %APPDATA%\\" + marker.parent.name + "\\" + MARKER)
    except BaseException:
        state["user_data_kept"] = {marker.parent.name: marker.is_file() for marker in markers}
        state["uninstall_display_names"] = sorted(v.get("DisplayName", "?") for _n, v in uninstall_entries(winreg))
        print("windows smoke state: " + redact(json.dumps(state, ensure_ascii=False, sort_keys=True)))
        raise
    finally:
        for marker in markers:
            marker.unlink(missing_ok=True)


# ---------------------------------------------------------------- macOS

def detach(mountpoint):
    for extra in ([], ["-force"]):
        if subprocess.run(["hdiutil", "detach", str(mountpoint), "-quiet", *extra], check=False).returncode == 0:
            return
        time.sleep(2)
    raise SmokeError("could not detach the installer image")


def launch(app, scratch):
    executable = app / "Contents" / "MacOS" / PRODUCT
    home = scratch / "home"
    home.mkdir()
    env = dict(os.environ)
    for name in ("PYTHONPATH", "PYTHONHOME", "MYCRM_DESKTOP_CONTROL", "MYCRM_JOBS_ALLOW_REAL_CLI"):
        env.pop(name, None)
    env["HOME"] = str(home)
    env["MYCRM_AGENT_HOME"] = str(scratch / "agent-home")
    user_data = scratch / "user-data"
    log_path = scratch / "app.log"
    with open(log_path, "wb") as log:
        # Electron ignores HOME for userData on macOS; keep its profile inside the scratch folder too.
        process = subprocess.Popen([str(executable), "--user-data-dir=" + str(user_data)], cwd=scratch, env=env,
                                   stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                   start_new_session=True)
        try:
            try:
                code = process.wait(timeout=LAUNCH_SECONDS)
            except subprocess.TimeoutExpired:
                code = None
            if code is not None:
                tail = log_path.read_text(encoding="utf-8", errors="replace")[-800:]
                raise SmokeError("app exited " + str(code) + " within " + str(LAUNCH_SECONDS) + "s: " + tail)
            if not (user_data / "logs").is_dir():
                raise SmokeError("app did not reach start-up (no diagnostic log folder in its profile)")
            print("app launched with isolated home and profile, reached start-up, stayed up " + str(LAUNCH_SECONDS) + "s")
        finally:
            how = "already exited"
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=20)
                    how = "terminated"
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                    how = "killed"
            try:
                os.killpg(process.pid, signal.SIGKILL)  # leftover Electron helpers in the same session
            except (ProcessLookupError, PermissionError):
                pass
            print("app stop: " + how)


def mac(installer, version):
    with tempfile.TemporaryDirectory(prefix="install-smoke-") as temp:
        scratch = Path(temp).resolve()
        mountpoint = scratch / "mnt"
        mountpoint.mkdir()
        applications = scratch / "Applications"
        applications.mkdir()
        subprocess.run(["hdiutil", "attach", str(installer), "-mountpoint", str(mountpoint),
                        "-nobrowse", "-readonly", "-noautoopen", "-quiet"], check=True)
        try:
            apps = sorted(mountpoint.glob("*.app"))
            if [a.name for a in apps] != [PRODUCT + ".app"]:
                raise SmokeError("installer image must hold exactly " + PRODUCT + ".app")
            app = applications / apps[0].name
            subprocess.run(["ditto", str(apps[0]), str(app)], check=True)
        finally:
            detach(mountpoint)
        print("installed: " + installer.name + " copied " + app.name + " to a scratch Applications folder")
        subprocess.run(["codesign", "--verify", "--deep", "--strict", str(app)], check=True)
        print("codesign verified: installed " + app.name)
        smoke(app / "Contents" / "Resources" / "agent" / "mycrm-agent", version)
        print("installed sidecar: --desktop-info contract matches, --help and status exit 0")
        launch(app, scratch)


RUNNERS = {"win32": windows, "darwin": mac}


def main(directory, platform=None):
    platform = platform or sys.platform
    if platform not in RUNNERS:
        raise SmokeError("install smoke supports Windows and macOS only")
    version = app_version()
    installer = installer_for(directory, platform, version)
    print("install smoke: " + installer.name)
    RUNNERS[platform](installer, version)
    print("install smoke passed: " + installer.name)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path, default=ROOT / "release/desktop", nargs="?")
    try:
        main(parser.parse_args().directory)
    except Exception as error:  # report redacted, never the raw traceback with local paths
        print("::error::install smoke failed: " + redact(type(error).__name__ + ": " + str(error),
                                                         extra=[("repo", ROOT)]))
        sys.exit(1)
