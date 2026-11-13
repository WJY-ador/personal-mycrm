"""AI 연결(명세 2026-11-13 1.3) — 이 PC 에서 공급자 CLI 인증이 되어 있는지, 로그인 띄우기, 로컬 끊기 표시.

AI 연결 = 그 PC 에서 공급자 CLI 가 로그인되어 있고, 사용자가 이 PC 에서 그 공급자를 끊지 않았음.
- 실행 파일 이름과 인자는 이 파일의 PROVIDERS, TERMINAL 한 곳에만 둔다. 앱(desktop)은 `ai-status`, `ai-connect`,
  `ai-disconnect` 하위 명령으로 부르고, chat 은 시작 때와 턴마다 같은 status() 를 쓴다.
- 상태 낱말(서버 계약 hello.ai_links 와 같다): linked(CLI 로그인 됨, 끊기 표시 없음) · signed_out(CLI 있음, 로그인 안 됨)
  · off(이 PC 의 끊기 표시) · missing(CLI 없음, 또는 chat 이 실행을 거절할 CLI). 이유는 짧은 code 로 따로 둔다.
- CLI 는 chat 과 같은 환경(chat_claude.ClaudeProviderFactory._clean_env)과 같은 작업 폴더(에이전트 홈)로 돈다.
  그래야 "인증됨" 판정이 실제 대화 실행과 어긋나지 않는다. API 키 환경 변수는 넘기지 않는다.
- CLI 출력: 로그인은 읽지 않는다. 상태는 claude 의 authMethod 하나만 읽고 나머지(계정, 이메일)는 버린다.
  MyCRM 은 인증 정보를 저장하거나 서버로 보내지 않는다. 공급자 CLI 가 인증을 보관한다(재시작, 잠금, 업데이트 뒤에도).
- 끊기는 로컬 표시다(USE_FILE). 공급자 로그아웃은 하지 않는다. 파일이 깨졌으면 모든 공급자를 끊긴 것으로 본다.

공식 문서(code.claude.com/docs/en/cli-reference, 2026-11-13 확인): `claude auth status` 는 JSON 을 내고 로그인이면
exit 0, 아니면 1. JSON 의 authMethod ∈ none, claude.ai, oauth_token, api_key, api_key_helper, third_party.
`claude auth login` 기본은 Claude 구독(--claudeai).
미확인(2026-11-13): `claude auth login` 이 TTY 없이(앱 자식 프로세스) 끝까지 도는지 — 그래서 로그인은 3초마다 상태를 보며
최대 5분 기다리고, 로그인 프로세스가 곧바로 실패하면 시스템 터미널로 같은 명령을 띄운다(TERMINAL).
`codex login status` 의 exit code 는 --help 에 없다. exit 0 = linked, 1 = signed_out 으로 둔다(메인 판정).
"""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
import time

from . import osutil

# 공급자별 실행 파일 이름과 인자. 여기 밖에서 공급자 CLI 인자를 만들지 않는다.
PROVIDERS = {
    "claude": {"binary": "claude", "status": ("auth", "status", "--json"), "login": ("auth", "login", "--claudeai")},
    "codex": {"binary": "codex", "status": ("login", "status"), "login": ("login",)},
}
# 로그인 프로세스가 TTY 없이 곧바로 실패하면 같은 명령을 띄울 시스템 터미널. {script}: 명령을 담은 .command 파일.
# Windows 는 cmd 를 거치지 않고 공급자 실행 파일(.exe)을 새 콘솔 창으로 바로 띄운다({path} {args}, CREATE_NEW_CONSOLE).
TERMINAL = {
    "darwin": ("/usr/bin/open", "-a", "Terminal", "{script}"),
    "win32": ("{path}", "{args}"),
}
CREATE_NEW_CONSOLE = getattr(subprocess, "CREATE_NEW_CONSOLE", 0x10)
# 구독 인증만 연결로 본다. API 키, 클라우드 공급자 인증은 종량제라 연결로 치지 않는다(signed_out, code unsupported-auth).
READY_METHODS = frozenset({"claude.ai", "oauth_token"})
# 상태 낱말(서버 계약 hello.ai_links, 앱, 화면이 같은 낱말을 쓴다).
STATES = ("linked", "signed_out", "off", "missing")
CODE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,47}$")
STATUS_TIMEOUT = 20
LOGIN_POLL = 3           # 로그인 중 상태 확인 간격(초)
LOGIN_WAIT = 300         # 로그인 끝을 기다리는 최대 시간(초)
LOGIN_QUICK_FAIL = 10    # 이 안에 로그인 프로세스가 실패로 끝나면 TTY 가 필요한 것으로 보고 터미널로 다시 띄운다
STATUS_OUTPUT_MAX = 64 * 1024
USE_FILE = "ai-connection.json"

# 앱은 GUI 로 떠서 PATH 가 짧다(macOS 는 /usr/bin:/bin:/usr/sbin:/sbin). 표준 설치 위치를 PATH 뒤에 본다.
_STANDARD_DIRS = {
    "darwin": ("~/.local/bin", "~/.claude/local", "~/.npm-global/bin", "/opt/homebrew/bin", "/usr/local/bin"),
    "linux": ("~/.local/bin", "~/.claude/local", "~/.npm-global/bin", "/usr/local/bin", "/usr/bin"),
    "win32": ("~/.local/bin",),
}
# 개발 도구가 PATH 앞에 끼우는 대리 실행 파일 폴더는 건너뛴다(desktop cli-discovery 와 같은 규칙).
_SKIP_PARTS = (os.sep + ".cmuxterm" + os.sep + "cmux-cli-shims", os.sep + ".codex" + os.sep + "tmp")


def _platform(value=None) -> str:
    p = value or sys.platform
    return "win32" if p.startswith("win") else "darwin" if p == "darwin" else "linux"


def discover(provider: str, *, path_value=None, platform=None, user_home=None) -> str | None:
    """PATH 와 표준 설치 위치에서 공급자 실행 파일을 찾아 실제 경로(링크를 따라간 절대 경로)를 돌려준다."""
    spec = PROVIDERS.get(provider)
    if spec is None:
        return None
    plat = _platform(platform)
    home = user_home or os.path.expanduser("~")
    name = spec["binary"] + (".exe" if plat == "win32" else "")
    dirs = []
    for d in str(os.environ.get("PATH", "") if path_value is None else path_value).split(os.pathsep):
        if not d or not os.path.isabs(d) or d == os.sep or any(part in d + os.sep for part in _SKIP_PARTS):
            continue
        dirs.append(os.path.normpath(d))
    for d in _STANDARD_DIRS[plat]:
        dirs.append(os.path.join(home, d[2:]) if d.startswith("~/") else d)
    for d in dirs:
        candidate = os.path.join(d, name)
        try:
            resolved = os.path.realpath(candidate)
            if os.path.isabs(resolved) and os.path.isfile(resolved) and os.access(resolved, os.X_OK):
                return resolved
        except OSError:
            continue
    return None


def configured_path(provider: str, cfg: dict) -> str | None:
    """설정에 저장된 실행 파일 경로(있고 실행 가능한 파일일 때만)."""
    summary = cfg.get("summary") if isinstance(cfg, dict) else None
    key = {"claude": "cli_path", "codex": "codex_cli_path"}.get(provider)
    value = summary.get(key) if isinstance(summary, dict) and key else None
    if isinstance(value, str) and os.path.isabs(value) and "\x00" not in value:
        try:
            if os.path.isfile(value) and os.access(value, os.X_OK):
                return value
        except OSError:
            return None
    return None


def cli_path(provider: str, cfg: dict, **discover_kw) -> str | None:
    return configured_path(provider, cfg) or discover(provider, **discover_kw)


def trusted(provider: str, path: str) -> bool:
    """chat 이 실행 전에 거는 같은 검사(링크, 파일, 폴더 소유자와 쓰기 권한 — chat_claude.resolve_cli_path). Claude, Codex 둘 다.
    통과 못 하면 연결로 치지 않고 실행하지 않는다. 여기서 거르지 않으면 상태는 ready 인데 chat 이 시작 때 claude-runtime 으로 통째로 멈춘다."""
    if provider not in PROVIDERS:
        return False
    from .chat_claude import ClaudeProviderUnavailable, resolve_cli_path
    try:
        resolve_cli_path(path)
        return True
    except ClaudeProviderUnavailable:
        return False


def clean_env(source=None) -> dict:
    """chat 이 공급자 CLI 를 돌리는 환경과 같은 것(허용 목록만, API 키 없음)."""
    from .chat_claude import ClaudeProviderFactory
    return ClaudeProviderFactory._clean_env(dict(os.environ if source is None else source))


# ---- 로컬 끊기 표시 ----------------------------------------------------------------------------
def _use_file(home: str) -> str:
    return os.path.join(home, USE_FILE)


def read_off(home: str) -> frozenset:
    """끊긴 공급자. 파일이 없으면 없음, 읽지 못하거나 꼴이 틀리면 전부(닫힌 쪽으로 실패)."""
    try:
        with open(_use_file(home), "r", encoding="utf-8") as f:
            raw = f.read(4097)
    except FileNotFoundError:
        return frozenset()
    except OSError:
        return frozenset(PROVIDERS)
    try:
        data = json.loads(raw) if len(raw) <= 4096 else None
        off = data.get("off") if isinstance(data, dict) else None
        if not isinstance(off, list) or not all(isinstance(p, str) and p in PROVIDERS for p in off):
            raise ValueError("shape")
        return frozenset(off)
    except ValueError:
        return frozenset(PROVIDERS)


def set_off(home: str, provider: str, off: bool) -> None:
    if provider not in PROVIDERS:
        raise ValueError("provider")
    # 깨진 파일은 전부 끊긴 것으로 읽힌다. 이번 요청의 공급자만 바꾸고 나머지는 끊긴 채 다시 쓴다.
    current = set(read_off(home))
    if off:
        current.add(provider)
    else:
        current.discard(provider)
    osutil.ensure_private_dir(home)
    osutil.atomic_write(_use_file(home), json.dumps({"version": 1, "off": sorted(current)}).encode("utf-8"))


# ---- 상태와 로그인 ----------------------------------------------------------------------------
def link(state: str, code: str | None = None) -> dict:
    return {"state": state, "code": code if isinstance(code, str) and CODE.fullmatch(code) else None}


def _classify(provider: str, rc: int, output: bytes) -> dict:
    if rc == 1:
        return link("signed_out")
    if rc != 0:
        return link("signed_out", "status-exit-" + str(rc if rc >= 0 else "signal"))
    if provider != "claude":
        return link("linked")
    try:
        data = json.loads(output[:STATUS_OUTPUT_MAX].decode("utf-8"))
        method = data.get("authMethod") if isinstance(data, dict) else None
    except (ValueError, UnicodeError):
        return link("signed_out", "status-unreadable")
    if method in READY_METHODS:
        return link("linked")
    if method == "none":
        return link("signed_out")
    return link("signed_out", "unsupported-auth" if isinstance(method, str) else "status-unreadable")


def status(provider: str, cfg: dict, home: str, *, run=subprocess.run, env=None, off=None, probe=True, **discover_kw) -> dict:
    """한 공급자의 AI 연결 {"state": STATES 낱말, "code": 이유 또는 None}. 예외를 내지 않는다.
    probe=False = 공급자 CLI 를 실행하지 않는다(파일 찾기와 신뢰 검사만). CLI 가 있으면 signed_out, code unchecked
    (Codex 가 아직 준비되지 않은 동안의 자동 확인 — 사용자가 ai-connect 를 누를 때만 실행한다, cli.auto_probe)."""
    if provider not in PROVIDERS:
        return link("missing", "unknown-provider")
    if provider in (read_off(home) if off is None else off):
        return link("off")
    path = cli_path(provider, cfg, **discover_kw)
    if path is None:
        return link("missing")
    if not trusted(provider, path):
        return link("missing", "untrusted-cli")
    if not probe:
        return link("signed_out", "unchecked")
    try:
        done = run([path, *PROVIDERS[provider]["status"]], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                   stderr=subprocess.DEVNULL, env=clean_env() if env is None else env, cwd=home,
                   timeout=STATUS_TIMEOUT, shell=False, check=False)
        output = done.stdout if provider == "claude" and isinstance(done.stdout, bytes) else b""
        return _classify(provider, done.returncode, output)
    except subprocess.TimeoutExpired:
        return link("signed_out", "status-timeout")
    except (OSError, subprocess.SubprocessError, ValueError):
        return link("signed_out", "status-failed")


def statuses(cfg: dict, home: str, *, probe=PROVIDERS, **kw) -> dict:
    """모든 공급자 상태. probe = CLI 를 실행해 확인할 공급자(나머지는 실행하지 않는다, status probe=False)."""
    off = read_off(home)
    return {p: status(p, cfg, home, off=off, probe=p in probe, **kw) for p in PROVIDERS}


def links(states: dict) -> dict:
    """hello.ai_links 꼴 {공급자: 상태 낱말}."""
    return {p: v["state"] for p, v in states.items() if p in PROVIDERS and isinstance(v, dict) and v.get("state") in STATES}


def _open_terminal(provider: str, path: str, home: str, platform: str, popen, env=None) -> bool:
    """같은 로그인 명령을 시스템 터미널에 띄운다(TTY 가 필요한 CLI). 띄웠으면 True."""
    form = TERMINAL.get(platform)
    if form is None:
        return False
    args = list(PROVIDERS[provider]["login"])
    if platform == "win32":
        # cmd 를 거치지 않는다(.cmd, .bat 는 CreateProcess 가 다시 cmd 로 돌리므로 띄우지 않는다). 새 콘솔이 입출력을 쓰도록 표준 입출력을 막지 않는다
        if not path.lower().endswith(".exe"):
            return False
        argv = []
        for x in form:
            argv.extend(args if x == "{args}" else [path] if x == "{path}" else [x])
        try:
            popen(argv, env=env, cwd=home, shell=False, close_fds=True, creationflags=CREATE_NEW_CONSOLE)
            return True
        except (OSError, ValueError):
            return False
    if platform == "darwin":
        script = os.path.join(home, f"ai-login-{provider}.command")
        body = "#!/bin/sh\nexec " + " ".join(shlex.quote(x) for x in [path, *args]) + "\n"
        osutil.atomic_write(script, body.encode("utf-8"))
        os.chmod(script, 0o700)
        argv = [x.replace("{script}", script) for x in form]
    else:
        argv = [x for x in form]
    try:
        popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, shell=False,
              close_fds=True)
        return True
    except (OSError, ValueError):
        return False


def login(provider: str, cfg: dict, home: str, *, popen=subprocess.Popen, env=None, sleep=time.sleep,
          clock=time.monotonic, platform=None, wait=LOGIN_WAIT, **kw) -> dict:
    """공급자 로그인을 띄우고(브라우저 인증) 3초마다 상태를 보며 최대 5분 기다린다. 출력은 읽지 않는다.
    로그인 프로세스가 LOGIN_QUICK_FAIL 안에 실패로 끝나면 시스템 터미널로 같은 명령을 띄우고 계속 기다린다."""
    discover_kw = {k: v for k, v in kw.items() if k in ("path_value", "user_home")}
    path = cli_path(provider, cfg, platform=platform, **discover_kw)
    if path is None:
        return link("missing")
    if not trusted(provider, path):
        return link("missing", "untrusted-cli")
    use_env = clean_env() if env is None else env
    check = lambda: status(provider, cfg, home, env=use_env, off=frozenset(), platform=platform, **kw)
    try:
        child = popen([path, *PROVIDERS[provider]["login"]], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                      stderr=subprocess.DEVNULL, env=use_env, cwd=home, shell=False, close_fds=True)
    except (OSError, ValueError):
        return link("signed_out", "login-start-failed")
    start, in_terminal, last = clock(), False, None
    try:
        while clock() - start < wait:
            sleep(LOGIN_POLL)
            last = check()
            if last["state"] == "linked":
                return last
            rc = child.poll() if child is not None else None
            if rc is None:
                continue
            if rc != 0 and not in_terminal and clock() - start <= LOGIN_QUICK_FAIL:
                in_terminal = _open_terminal(provider, path, home, _platform(platform), popen, use_env)
                child = None
                if in_terminal:
                    continue
            if not in_terminal:
                break
    finally:
        if child is not None and child.poll() is None:
            child.kill()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
    last = check()
    if last["state"] != "linked" and last["code"] is None:
        last = link(last["state"], "login-terminal" if in_terminal else "login-unfinished")
    return last
