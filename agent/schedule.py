"""launchd 예약 — 현재 사용자 LaunchAgent 하나.

- 주기 1시간(StartInterval 3600). 시작 지연 0~5분은 run-once --scheduled 가 안에서 준다(launchd 엔 지터가 없다).
- plist·명령줄·환경변수에 토큰을 넣지 않는다. 실행 경로·홈 경로는 절대 경로로 고정.
- 등록·해제는 멱등. 예약 해제는 원문·매핑 삭제와 별개.
- launchctl 호출은 주입 가능한 실행기로만(시험은 모의 실행기, 실제 등록 안 함).
- Windows는 현재 사용자 Task Scheduler 작업 하나를 명시적으로 등록한다.
"""
from __future__ import annotations

import os
import getpass
import hashlib
import xml.etree.ElementTree as ET
import plistlib
import subprocess
import sys

from . import osutil

LABEL = "local.mycrm.agent"
INTERVAL_SEC = 3600
LAUNCHCTL = "/bin/launchctl"


class ScheduleError(RuntimeError):
    pass


def _run(argv):
    return subprocess.run(argv, capture_output=True, text=True, timeout=30)


def package_parent() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def plist_path(launch_agents_dir: str | None = None) -> str:
    d = launch_agents_dir or os.path.join(os.path.expanduser("~"), "Library", "LaunchAgents")
    return os.path.join(d, LABEL + ".plist")


def command_arguments(*, python: str, home: str, frozen: bool | None = None) -> list[str]:
    """The frozen entrypoint already is `agent`; it must not invoke `-m agent`."""
    is_frozen = getattr(sys, "frozen", False) if frozen is None else frozen
    return [python] + ([] if is_frozen else ["-m", "agent"]) + [
        "--home", home, "run-once", "--scheduled"]


def build_plist(*, python: str, home: str, workdir: str, frozen: bool | None = None) -> bytes:
    for p in (python, home, workdir):
        if not os.path.isabs(p):
            raise ScheduleError("paths must be absolute")
    logs = os.path.join(home, "logs")
    d = {
        "Label": LABEL,
        "ProgramArguments": command_arguments(python=python, home=home, frozen=frozen),
        "WorkingDirectory": workdir,
        "StartInterval": INTERVAL_SEC,
        "RunAtLoad": False,
        "ProcessType": "Background",
        "LowPriorityIO": True,
        "Nice": 10,
        "StandardOutPath": os.path.join(logs, "agent.out.log"),
        "StandardErrorPath": os.path.join(logs, "agent.err.log"),
        "EnvironmentVariables": {"PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1"},
    }
    return plistlib.dumps(d, fmt=plistlib.FMT_XML, sort_keys=True)


def install(*, home: str, python: str | None = None, workdir: str | None = None,
            launch_agents_dir: str | None = None, runner=None, load: bool = True) -> str:
    """'installed' | 'unchanged'. 파일이 같으면 다시 쓰지 않는다."""
    if osutil.IS_WINDOWS:
        return _windows_install(home=home, python=python, workdir=workdir, runner=runner, load=load)
    if not osutil.IS_MAC:
        raise ScheduleError("no supported scheduler on this OS")
    runner = runner or _run
    python = python or os.path.realpath(sys.executable)
    workdir = workdir or (os.path.dirname(python) if getattr(sys, "frozen", False) else package_parent())
    data = build_plist(python=python, home=os.path.abspath(home), workdir=workdir)
    path = plist_path(launch_agents_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    osutil.ensure_private_dir(os.path.join(os.path.abspath(home), "logs"))
    previous = None
    if os.path.exists(path):
        with open(path, "rb") as f:
            previous = f.read()
        if previous == data:
            return "unchanged"
    osutil.atomic_write(path, data)
    os.chmod(path, 0o644)   # launchd 는 소유자 쓰기만 허용된 plist 를 읽는다. 토큰은 없다
    if load:
        dom = f"gui/{os.getuid()}"
        runner([LAUNCHCTL, "bootout", dom + "/" + LABEL])           # 이전 판 내림(없으면 실패 무시)
        r = runner([LAUNCHCTL, "bootstrap", dom, path])
        if getattr(r, "returncode", 0) != 0:
            if previous is None:
                os.unlink(path)
            else:
                osutil.atomic_write(path, previous)
                runner([LAUNCHCTL, "bootstrap", dom, path])
            raise ScheduleError(f"launchctl bootstrap failed (exit {r.returncode})")
    return "installed"


def remove(*, launch_agents_dir: str | None = None, runner=None, unload: bool = True) -> str:
    """'removed' | 'absent'."""
    if osutil.IS_WINDOWS:
        runner = runner or _run
        if not _windows_installed(runner):
            return "absent"
        _checked(runner, [_schtasks(), "/Delete", "/TN", _windows_task_name(), "/F"])
        return "removed"
    if not osutil.IS_MAC:
        raise ScheduleError("no supported scheduler on this OS")
    runner = runner or _run
    path = plist_path(launch_agents_dir)
    if unload:
        runner([LAUNCHCTL, "bootout", f"gui/{os.getuid()}/{LABEL}"])
    if os.path.exists(path):
        os.unlink(path)
        return "removed"
    return "absent"


def installed(launch_agents_dir: str | None = None, *, runner=None) -> bool:
    if osutil.IS_WINDOWS:
        return _windows_installed(runner or _run)
    if not osutil.IS_MAC:
        return False
    return os.path.exists(plist_path(launch_agents_dir))


def _schtasks() -> str:
    return os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "schtasks.exe")


def _windows_task_name() -> str:
    # Task Scheduler names are machine-wide; isolate each user's registration.
    identity = os.path.normcase(os.path.expanduser("~")).encode("utf-8")
    return "MyCRM-Agent-" + hashlib.sha256(identity).hexdigest()[:16]


def _checked(runner, argv):
    try:
        result = runner(argv)
    except (OSError, subprocess.SubprocessError):
        raise ScheduleError("Task Scheduler call failed") from None
    if result.returncode != 0:
        raise ScheduleError("Task Scheduler call failed (exit " + str(result.returncode) + ")")
    return result


def _windows_installed(runner) -> bool:
    try:
        result = runner([_schtasks(), "/Query", "/TN", _windows_task_name(), "/XML"])
    except (OSError, subprocess.SubprocessError):
        raise ScheduleError("Task Scheduler query failed") from None
    if result.returncode == 0:
        return True
    # schtasks uses 1 for a task that does not exist. Other failures are surfaced.
    if result.returncode == 1:
        return False
    raise ScheduleError("Task Scheduler query failed (exit " + str(result.returncode) + ")")


def build_task_xml(*, python: str, home: str, workdir: str,
                   user: str, frozen: bool | None = None) -> bytes:
    import ntpath
    if not all(ntpath.isabs(p) for p in (python, home, workdir)):
        raise ScheduleError("paths must be absolute")
    if not user or any(ord(c) < 32 for c in user):
        raise ScheduleError("user identity is required")
    ns = "http://schemas.microsoft.com/windows/2004/02/mit/task"
    ET.register_namespace("", ns)
    def node(parent, tag, value=None, **attributes):
        e = ET.SubElement(parent, "{" + ns + "}" + tag, attributes)
        if value is not None:
            e.text = value
        return e
    task = ET.Element("{" + ns + "}Task", {"version": "1.2"})
    triggers = node(task, "Triggers")
    calendar = node(triggers, "CalendarTrigger")
    repetition = node(calendar, "Repetition")
    node(repetition, "Interval", "PT1H")
    node(repetition, "Duration", "P1D")
    node(repetition, "StopAtDurationEnd", "false")
    node(calendar, "StartBoundary", "2020-01-01T00:00:00")
    node(calendar, "Enabled", "true")
    node(node(calendar, "ScheduleByDay"), "DaysInterval", "1")
    principals = node(task, "Principals")
    principal = node(principals, "Principal", id="Author")
    node(principal, "UserId", user)
    node(principal, "LogonType", "InteractiveToken")
    node(principal, "RunLevel", "LeastPrivilege")
    settings = node(task, "Settings")
    node(settings, "MultipleInstancesPolicy", "IgnoreNew")
    node(settings, "DisallowStartIfOnBatteries", "false")
    node(settings, "StopIfGoingOnBatteries", "false")
    node(settings, "StartWhenAvailable", "false")
    node(settings, "ExecutionTimeLimit", "PT30M")
    actions = node(task, "Actions", Context="Author")
    action = node(actions, "Exec")
    argv = command_arguments(python=python, home=home, frozen=frozen)
    node(action, "Command", argv[0])
    node(action, "Arguments", subprocess.list2cmdline(argv[1:]))
    node(action, "WorkingDirectory", workdir)
    return ET.tostring(task, encoding="utf-16", xml_declaration=True)


def _windows_install(*, home, python=None, workdir=None, runner=None, load=True):
    runner = runner or _run
    python = python or os.path.realpath(sys.executable)
    workdir = workdir or (os.path.dirname(python) if getattr(sys, "frozen", False) else package_parent())
    user = getpass.getuser()
    domain = os.environ.get("USERDOMAIN")
    if domain:
        user = domain + "\\" + user
    data = build_task_xml(python=python, home=os.path.abspath(home), workdir=workdir, user=user)
    directory = os.path.join(home, "schedule")
    osutil.ensure_private_dir(directory)
    path = os.path.join(directory, "agent-task.xml")
    previous = None
    if os.path.exists(path):
        with open(path, "rb") as f:
            previous = f.read()
    if previous == data and (not load or _windows_installed(runner)):
        return "unchanged"
    osutil.atomic_write(path, data)
    try:
        if load:
            _checked(runner, [_schtasks(), "/Create", "/TN", _windows_task_name(), "/XML", path, "/F"])
    except ScheduleError:
        if previous is None:
            os.unlink(path)
        else:
            osutil.atomic_write(path, previous)
        raise
    return "installed"
