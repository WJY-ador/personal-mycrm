"""AI 연결(명세 2026-11-13 1.3) — 이 PC 에서 공급자 CLI 인증이 되어 있는지, 로그인 띄우기, 로컬 끊기 표시.

AI 연결 = 그 PC 에서 공급자 CLI 가 로그인되어 있고, 사용자가 이 PC 에서 그 공급자를 끊지 않았음.
- 실행 파일 이름과 인자는 이 파일의 PROVIDERS 한 곳에만 둔다. 앱(desktop)은 `ai-status`, `ai-connect`,
  `ai-disconnect` 하위 명령으로 부르고, chat 은 시작 때 같은 status() 를 쓴다.
- CLI 는 chat 과 같은 환경(chat_claude.ClaudeProviderFactory._clean_env)과 같은 작업 폴더(에이전트 홈)로 돈다.
  그래야 "인증됨" 판정이 실제 대화 실행과 어긋나지 않는다. API 키 환경 변수는 넘기지 않는다.
- CLI 출력: 로그인은 읽지 않는다. 상태는 claude 의 authMethod 하나만 읽고 나머지(계정, 이메일)는 버린다.
  MyCRM 은 인증 정보를 저장하거나 서버로 보내지 않는다. 공급자 CLI 가 인증을 보관한다(재시작, 잠금, 업데이트 뒤에도).
- 끊기는 로컬 표시다(USE_FILE). 공급자 로그아웃은 하지 않는다. 파일이 깨졌으면 모든 공급자를 끊긴 것으로 본다.

공식 문서(code.claude.com/docs/en/cli-reference, 2026-11-13 확인): `claude auth status` 는 JSON 을 내고 로그인이면
exit 0, 아니면 1. JSON 의 authMethod ∈ none, claude.ai, oauth_token, api_key, api_key_helper, third_party.
`claude auth login` 기본은 Claude 구독(--claudeai). codex 의 `codex login status` exit code 는 --help 에 없어 미확인이다.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

from . import osutil

# 공급자별 실행 파일 이름과 인자. 여기 밖에서 공급자 CLI 인자를 만들지 않는다.
PROVIDERS = {
    "claude": {"binary": "claude", "status": ("auth", "status", "--json"), "login": ("auth", "login", "--claudeai")},
    "codex": {"binary": "codex", "status": ("login", "status"), "login": ("login",)},
}
# 구독 인증만 연결로 본다. API 키, 클라우드 공급자 인증은 종량제라 연결로 치지 않는다(unsupported).
READY_METHODS = frozenset({"claude.ai", "oauth_token"})
# 상태 낱말(앱, 서버 보고, 화면이 같은 낱말을 쓴다).
STATES = ("ready", "signed-out", "missing", "off", "unsupported", "error")
STATUS_TIMEOUT = 20
LOGIN_TIMEOUT = 600
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
    """chat 이 실행 전에 거는 같은 검사(Claude: 링크, 파일, 폴더 소유자와 쓰기 권한). 통과 못 하면 연결로 치지 않는다.
    여기서 거르지 않으면 상태는 ready 인데 chat 이 시작 때 claude-runtime 으로 통째로 멈춘다."""
    if provider != "claude":
        return True
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
def _classify(provider: str, code: int, output: bytes) -> str:
    if code == 1:
        return "signed-out"
    if code != 0:
        return "error"
    if provider != "claude":
        return "ready"
    try:
        data = json.loads(output[:STATUS_OUTPUT_MAX].decode("utf-8"))
        method = data.get("authMethod") if isinstance(data, dict) else None
    except (ValueError, UnicodeError):
        return "error"
    if method in READY_METHODS:
        return "ready"
    if method == "none":
        return "signed-out"
    return "unsupported" if isinstance(method, str) else "error"


def status(provider: str, cfg: dict, home: str, *, run=subprocess.run, env=None, off=None, **discover_kw) -> str:
    """한 공급자의 AI 연결 상태(STATES 의 낱말 하나). 예외를 내지 않는다."""
    if provider not in PROVIDERS:
        return "error"
    if provider in (read_off(home) if off is None else off):
        return "off"
    path = cli_path(provider, cfg, **discover_kw)
    if path is None:
        return "missing"
    if not trusted(provider, path):
        return "error"
    spec = PROVIDERS[provider]
    try:
        done = run([path, *spec["status"]], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                   stderr=subprocess.DEVNULL, env=clean_env() if env is None else env, cwd=home,
                   timeout=STATUS_TIMEOUT, shell=False, check=False)
        output = done.stdout if provider == "claude" and isinstance(done.stdout, bytes) else b""
        return _classify(provider, done.returncode, output)
    except (OSError, subprocess.SubprocessError, ValueError):
        return "error"


def statuses(cfg: dict, home: str, **kw) -> dict:
    off = read_off(home)
    return {p: status(p, cfg, home, off=off, **kw) for p in PROVIDERS}


def login(provider: str, cfg: dict, home: str, *, popen=subprocess.Popen, env=None, timeout=LOGIN_TIMEOUT,
          **discover_kw) -> str:
    """공급자 로그인을 띄우고(브라우저 인증) 끝나면 상태를 다시 본다. 출력은 읽지 않는다."""
    path = cli_path(provider, cfg, **discover_kw)
    if path is None:
        return "missing"
    if not trusted(provider, path):
        return "error"
    use_env = clean_env() if env is None else env
    try:
        child = popen([path, *PROVIDERS[provider]["login"]], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                      stderr=subprocess.DEVNULL, env=use_env, cwd=home, shell=False, close_fds=True)
    except (OSError, ValueError):
        return "error"
    try:
        child.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        child.kill()
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
    return status(provider, cfg, home, env=use_env, off=frozenset(), **discover_kw)
