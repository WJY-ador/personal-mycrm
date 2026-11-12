"""CLI — connect · validate · run-once · status · schedule install/remove · serve(원문 뷰어·--jobs 작업 실행) · disconnect
· migrate(실자료 이관 업로더) · chat(웹 「대화」 PC 연결 — PR 1 은 --fake 만).

사용: python3 -m agent [--home 경로] <명령> ...
출력엔 토큰·HMAC 키·원문·실명·URL 을 쓰지 않는다.
"""
from __future__ import annotations

import argparse
import codecs
import datetime as _dt
import getpass
import json
import os
import re
import sys

from . import AGENT_VERSION, chat_mcp_bridge, config as _config, contract, hmacid, keystore, osutil, runner, schedule, store as _store

EXIT_OK, EXIT_ERR, EXIT_USAGE, EXIT_HALT = 0, 1, 2, 3
CHAT_CLAUDE_PROVIDER_READY = False  # server+desktop launch lifecycle review gate; keep default OFF
CHAT_CODEX_PROVIDER_READY = False  # subscription home/login and production package trust are unverified


class Ctx:
    def __init__(self, home, *, ks_factory=None, getpass_fn=None, uploader_factory=None,
                 schedule_runner=None, launch_agents_dir=None, exec_runner=None, out=None, stdin=None,
                 jobs_adapter_factory=None, jobs_client_factory=None, jobs_serve_kw=None,
                 browser_open=None, login_timeout=None, chat_kw=None):
        self.paths = _config.Paths(home)
        self.ks_factory = ks_factory or keystore.for_platform
        self.getpass_fn = getpass_fn or getpass.getpass
        self.uploader_factory = uploader_factory
        self.schedule_runner = schedule_runner
        self.launch_agents_dir = launch_agents_dir
        self.exec_runner = exec_runner
        self.jobs_adapter_factory = jobs_adapter_factory    # (runner) → jobs 어댑터 — 시험은 fake
        self.jobs_client_factory = jobs_client_factory      # (server, token) → jobs.Client
        self.jobs_serve_kw = dict(jobs_serve_kw or {})      # 시험용 serve_jobs 인자(유예 등)
        self.browser_open = browser_open                    # 시스템 브라우저 열기 — 시험은 가짜
        self.login_timeout = login_timeout                  # 브라우저 로그인 기다림(초) — 기본 uploader.LOGIN_TIMEOUT
        self.chat_kw = dict(chat_kw or {})                  # 시험용 chat.ChatAgent 인자(connect·stopping·provider 등)
        self.out = out or sys.stdout
        self.stdin = stdin or sys.stdin

    def say(self, msg: str) -> None:
        print(msg, file=self.out)

    def keystore(self, cfg):
        return self.ks_factory(cfg.get("keychain_service") or _config.KEYCHAIN_SERVICE)


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python3 -m agent", description="my-crm 로컬 에이전트 " + AGENT_VERSION)
    p.add_argument("--home", help="에이전트 홈(기본: OS 사용자 디렉터리)")
    sub = p.add_subparsers(dest="cmd")

    c = sub.add_parser("connect", help="장치 연결 — 업로드 토큰을 Keychain 에 넣는다")
    c.add_argument("--server", required=True, help="서버 주소(https)")
    c.add_argument("--label", help="(덮어쓰기) 장치 이름 — 기본은 서버 값")
    c.add_argument("--hmac-namespace", help="(덮어쓰기) 키 공간 ID — 기본은 서버 값")
    c.add_argument("--policy-revision", type=int, help="(덮어쓰기) 정책 판 — 기본은 서버 값")
    c.add_argument("--axis", action="append", default=[], help="(덮어쓰기) 허용 축 항목 ID(여러 번)")
    cg = c.add_mutually_exclusive_group()
    cg.add_argument("--token-stdin", action="store_true", help="토큰을 표준 입력 한 줄로 받는다(화면 표시 없음)")
    cg.add_argument("--browser", action="store_true",
                    help="앱 없이 브라우저 로그인으로 연결(127.0.0.1 loopback, 장치 이름 = --label 또는 호스트 이름)")

    v = sub.add_parser("validate", help="설정·전송 대기 파일·지정 파일의 계약 검증")
    v.add_argument("files", nargs="*")

    r = sub.add_parser("run-once", help="수집·변환·검증·업로드 1회")
    r.add_argument("--scheduled", action="store_true", help="예약 실행(0~5분 지연, unattended)")
    r.add_argument("--no-upload", action="store_true", help="전송 대기까지만")
    r.add_argument("--no-rotate", action="store_true",
                   help="만료 전 Bearer 토큰 교체를 건너뛴다(데스크톱 앱 = 세션 교체를 쓴다)")
    r.add_argument("--resume", choices=("auth", "config", "account", "policy", "forbidden", "summary"),
                   help="사용자 조치 뒤 멈춤 해제")

    sub.add_parser("status", help="연결·대기·격리·예약 상태")

    cc = sub.add_parser("configure-cli", help="구독 CLI 실행 파일 경로 설정")
    choice = cc.add_mutually_exclusive_group(required=True)
    choice.add_argument("--path", help="설치된 Claude 실행 파일 절대 경로")
    choice.add_argument("--clear", action="store_true", help="저장된 CLI 경로만 지움")

    codex_cfg = sub.add_parser("configure-codex", help="Codex CLI 실행 파일과 명시 모델 ID 설정")
    codex_cfg.add_argument("--path", required=True, help="설치된 Codex 실행 파일 절대 경로")
    codex_cfg.add_argument("--model", action="append", required=True,
                           help="구독에서 확인한 모델 ID(여러 번 지정 가능, 최대 20개)")

    s = sub.add_parser("schedule", help="현재 사용자 예약(1시간마다)")
    s.add_argument("action", choices=("install", "remove"))

    sv = sub.add_parser("serve", help="원문 뷰어(127.0.0.1) · --jobs = 작업 실행(상주)")
    sv.add_argument("--port", type=int)
    sv.add_argument("--jobs", action="store_true", help="서버 작업을 받아 이 PC 의 claude -p 로 실행(상주, 종료 = SIGTERM·Ctrl+C)")

    d = sub.add_parser("disconnect", help="서버 토큰 폐기 + 로컬 업로드 토큰 제거")
    d.add_argument("--local-only", action="store_true", help="서버 폐기를 건너뛰고 로컬만 지운다")
    d.add_argument("--forget-hmac-key", action="store_true",
                   help="이 키 공간의 HMAC 키도 지운다(같은 사람 연결이 끊긴다)")

    ch = sub.add_parser("chat", help="웹 「대화」 — 서버에 WebSocket 으로 붙어 받은 턴을 이 PC 에서 실행(상주, 종료 = Ctrl+C)")
    ch.add_argument("--fake", action="store_true", help="모델 대신 정해진 가짜 대본으로 답한다(시험·측정용)")
    ch.add_argument("--consent-only", action="store_true", help="데스크톱 native 동의 요청만 중계한다(모델 실행 없음)")

    bridge = sub.add_parser("chat-mcp-bridge", help=argparse.SUPPRESS)
    bridge.add_argument("--agent-home", required=True)
    bridge.add_argument("--session-id", required=True)
    bridge.add_argument("--turn-id", required=True)
    bridge.add_argument("--device-id", required=True)
    bridge.add_argument("--provider", required=True, choices=("claude", "codex"))
    bridge.add_argument("--model", required=True)
    bridge.add_argument("--authorization-path", required=True)

    m = sub.add_parser("migrate", help="실자료 이관(board-migration/2) — login·logout·stage·status·cancel·receipt")
    ms = m.add_subparsers(dest="mcmd")
    ml = ms.add_parser("login", help="이관 토큰을 키 저장소에 넣는다(웹 이관 화면에서 발급)")
    mlg = ml.add_mutually_exclusive_group()
    mlg.add_argument("--token-stdin", action="store_true", help="토큰을 표준 입력 한 줄로 받는다(화면 표시 없음)")
    mlg.add_argument("--browser", action="store_true", help="브라우저 로그인으로 이관 토큰을 받는다(127.0.0.1 loopback)")
    ms.add_parser("logout", help="이 서버의 로컬 이관 토큰을 지운다")
    mst = ms.add_parser("stage", help="입력 JSONL 검증 → plan 만들기 → 청크 업로드 → seal → dry-run 요약")
    mst.add_argument("items", help="항목 JSONL(한 줄 = board-migration/2 항목 하나)")
    mst.add_argument("--source-instance", help="plan 의 source_instance(항목에 없을 때 채운다)")
    for name, hlp in (("status", "plan 상태·dry-run 집계"), ("cancel", "plan 취소(서버 스테이징 본문 삭제)")):
        ms.add_parser(name, help=hlp).add_argument("plan_id")
    mr = ms.add_parser("receipt", help="영수증 개수 · --verify 면 입력 항목과 대조(0 일치 / 1 불일치·오류 / 2 쓰는 법)")
    mr.add_argument("plan_id")
    mr.add_argument("--verify", metavar="ITEMS_JSONL", help="stage 에 쓴 같은 입력 파일")
    for sp in ms.choices.values():
        sp.add_argument("--server", required=True, help="서버 주소(https)")
    return p


# ---- 장치 토큰 교체(PC 연결 계획 §3 · M2) -------------------------------------------
ROTATE_BEFORE = _dt.timedelta(days=30)   # 만료 30일 전부터 run-once 때 자동 교체


def pending_token_account(source_instance_id: str) -> str:
    """교체 대기 토큰 계정 — rotate 로 받았지만 아직 서버 확인(첫 사용) 전인 새 토큰. 1개만(다음 교체가 덮어씀)."""
    return "upload-token-pending:" + source_instance_id


def _rotate_due(cfg: dict, now: _dt.datetime) -> bool:
    exp = cfg.get("token_expires_at")
    if isinstance(exp, str) and exp.endswith("Z"):
        exp = exp[:-1] + "+00:00"      # 3.9 fromisoformat 은 Z 를 못 읽는다
    try:
        at = _dt.datetime.fromisoformat(exp) if isinstance(exp, str) else None
    except ValueError:
        at = None
    if at is None or at.tzinfo is None:
        return False          # 만료를 모르면 교체하지 않는다
    return at - now <= ROTATE_BEFORE


def promote_pending(ctx: Ctx, cfg: dict, ks) -> str | None:
    """대기 토큰을 새 토큰으로 서버에 확인(GET device = 첫 사용)하고 Keychain 본 자리로 옮긴다.
    반환: None(대기 없음) · "promoted" · "discarded"(서버가 새 토큰을 안 받음 — 옛 토큰 그대로) · "deferred"(네트워크 등 — 다음에).
    KeyStoreError 는 그대로 올린다(본 자리 쓰기 실패 = 옛 토큰은 이미 무효일 수 있어 업로드를 멈춰야 한다)."""
    from .uploader import AUTH_CODES, DeviceError
    sid, server = cfg.get("source_instance_id"), cfg.get("server_url")
    if not sid or not server:
        return None
    acct = pending_token_account(sid)
    new = ks.get(acct)
    if not new:
        return None
    try:
        info = _uploader(ctx, server, new).device()
    except DeviceError as e:
        if e.kind == "auth" or e.code in AUTH_CODES:
            ks.delete(acct)        # 한 번도 쓰이지 않은 새 토큰 — 서버에서 옛 토큰은 아직 살아 있다(M2)
            return "discarded"
        return "deferred"
    if not isinstance(info, dict) or info.get("stream_id") != sid:
        return "deferred"
    # 여기서부터 서버는 옛 토큰을 무효로 본다 — 새 토큰을 본 자리로
    ks.set(_config.token_account(sid), new)
    ks.delete(acct)
    if isinstance(info.get("token_expires_at"), str):
        try:
            with osutil.FileLock(ctx.paths.lock("config")):
                cur = _config.load(ctx.paths)
                if cur.get("source_instance_id") == sid:
                    cur["token_expires_at"] = info["token_expires_at"]
                    _config.save(ctx.paths, cur)
        except (osutil.LockBusy, _config.ConfigError):
            pass               # 만료 표시만 늦어진다 — 다음 확인 때 고친다
    return "promoted"


ROTATE_REFUSED_BACKOFF = _dt.timedelta(hours=24)   # 서버가 교체를 거절하면 하루 한 번만 다시 묻는다(안내 반복 방지)
ROTATE_STATE_FILE = "rotate-state.json"            # {source_instance_id, refused_at, code} — 토큰 값 없음


def _rotate_refused_recently(ctx: Ctx, sid: str, now: _dt.datetime) -> bool:
    try:
        with open(os.path.join(ctx.paths.home, ROTATE_STATE_FILE), "r", encoding="utf-8") as f:
            st = json.load(f)
        at = _dt.datetime.fromisoformat(st["refused_at"])
    except (OSError, ValueError, KeyError, TypeError):
        return False
    if st.get("source_instance_id") != sid or at.tzinfo is None:
        return False
    return now - ROTATE_REFUSED_BACKOFF < at <= now + _dt.timedelta(minutes=5)   # 미래 시각(시계 어긋남)은 무시


def _set_rotate_refused(ctx: Ctx, sid: str | None, code: str, now: _dt.datetime) -> None:
    path = os.path.join(ctx.paths.home, ROTATE_STATE_FILE)
    try:
        if sid is None:
            if os.path.exists(path):
                os.remove(path)
            return
        data = {"source_instance_id": sid, "refused_at": now.isoformat(timespec="seconds"), "code": code}
        osutil.atomic_write(path, json.dumps(data, ensure_ascii=False, sort_keys=True).encode("utf-8"))
    except OSError:
        pass                   # 기록 실패면 다음 실행이 다시 묻는다 — 안내가 한 번 더 나올 뿐


def rotate_token(ctx: Ctx, cfg: dict, ks, *, now=None) -> str | None:
    """만료 30일 안이면 POST /api/device/rotate(Bearer 현 토큰) → 새 토큰을 대기 자리에 두고 바로 승격을 시도한다.
    반환: None(할 일 없음) · promote_pending 결과 · "rotate-<종류>[-코드]"(서버 거절·네트워크). 토큰 값은 반환·출력하지 않는다."""
    from .uploader import DeviceError
    sid, server = cfg.get("source_instance_id"), cfg.get("server_url")
    now = now or osutil.kst_now()
    if not sid or not server or not _rotate_due(cfg, now):
        return None
    if ks.get(pending_token_account(sid)):
        return promote_pending(ctx, cfg, ks)
    if _rotate_refused_recently(ctx, sid, now):
        return None            # 24시간 안에 거절됨 — 조용히 건너뛴다
    old = ks.get(_config.token_account(sid))
    if not old:
        return None
    try:
        res = _uploader(ctx, server, old).rotate()
    except DeviceError as e:
        r = "rotate-" + e.kind + (("-" + e.code) if e.code else "")
        if e.kind != "network":    # 네트워크는 다음 실행에 바로 다시
            _set_rotate_refused(ctx, sid, e.code or ("http-" + str(e.status)), now)
        return r
    new = res.get("token") if isinstance(res, dict) else None
    try:
        stream_id, _tid = contract.parse_token(new if isinstance(new, str) else "")
    except contract.ContractError:
        _set_rotate_refused(ctx, sid, "bad-response", now)
        return "rotate-bad-response"
    if stream_id != sid or res.get("stream_id") not in (None, sid):
        _set_rotate_refused(ctx, sid, "bad-response", now)
        return "rotate-bad-response"
    _set_rotate_refused(ctx, None, "", now)
    ks.set(pending_token_account(sid), new)
    return promote_pending(ctx, cfg, ks)


ROTATE_MESSAGES = {
    "promoted": "토큰 교체: 새 토큰으로 바꿨어요(Keychain, 표시 안 함).",
    "discarded": "토큰 교체: 서버가 새 토큰을 받지 않아 버렸어요. 지금 토큰을 그대로 써요.",
    "deferred": "토큰 교체: 새 토큰 확인을 다음 실행으로 미뤘어요(지금 토큰은 그대로 유효).",
    "rotate-bad-response": "토큰 교체: 서버 응답 모양이 맞지 않아 건너뛰었어요.",
}


def _rotate_message(r: str) -> str:
    if r in ROTATE_MESSAGES:
        return ROTATE_MESSAGES[r]
    if "DEVICE-REVOKED" in r or "TOKEN-REVOKED" in r:
        return "토큰 교체: 이 PC 연결이 해제됐어요 — 대화에서 「PC 연결해 줘」로 다시 연결하세요."
    if r.startswith("rotate-network"):
        return "토큰 교체: 서버에 닿지 못해 다음 실행으로 미뤘어요."
    if r.startswith("rotate-auth"):
        # 서버 계약: 90일 동안 업로드가 없던 장치는 401 TOKEN-EXPIRED 로 교체를 거절한다
        return ("토큰 교체: 서버가 거절했어요(" + r[len("rotate-auth-"):] + "). 지금 토큰은 만료까지 그대로 써요 — "
                "만료 전에 다시 연결하세요(앱에서 수집 켜기 · 대화에서 「PC 연결해 줘」).")
    return "토큰 교체: 서버가 거절했어요(" + r[len("rotate-"):] + "). 지금 토큰은 만료까지 그대로 써요."


def _with_run_lock(ctx: Ctx, fn):
    """run 잠금 안에서 fn() — 다른 run-once 가 옛 토큰으로 보내는 중에 새 토큰을 쓰지 않게. 잠금이 바쁘면 None."""
    ctx.paths.ensure()
    lock = osutil.FileLock(ctx.paths.lock("run"))
    try:
        lock.acquire()
    except osutil.LockBusy:
        return None
    try:
        return fn()
    finally:
        lock.release()


def browser_token(ctx: Ctx, server: str, scope: str, *, client_name=None):
    """브라우저 로그인으로 토큰 받기(connect·migrate login 공용). 실패면 안내를 출력하고 None. 토큰은 출력하지 않는다."""
    from .uploader import LOGIN_TIMEOUT, LoginError, browser_login, explain_login_error
    try:
        return browser_login(server, scope, client_name=client_name, open_browser=ctx.browser_open, say=ctx.say,
                             timeout=ctx.login_timeout or LOGIN_TIMEOUT)
    except LoginError as e:
        for line in explain_login_error(e):
            ctx.say(line)
        return None


# ---- 명령 ---------------------------------------------------------------------
def _uploader(ctx: Ctx, server: str, token: str):
    from .uploader import Uploader
    return (ctx.uploader_factory or Uploader)(server, token, timeout=30)


def cmd_connect(ctx: Ctx, a) -> int:
    """토큰만 받는다. 입력원·정책·키 공간은 GET /api/imports/device 로 받아 확인한다.
    --hmac-namespace·--policy-revision·--axis·--label 은 서버 값을 덮어쓸 때만 쓴다."""
    from .uploader import DeviceError
    server = _config.check_server_url(a.server)
    if a.hmac_namespace is not None and not _config.NAMESPACE_RE.match(a.hmac_namespace):
        ctx.say("키 공간 ID 형식이 맞지 않아요.")
        return EXIT_USAGE
    if a.policy_revision is not None and a.policy_revision < 1:
        ctx.say("정책 판은 1 이상이에요.")
        return EXIT_USAGE
    for ax in a.axis:
        if not contract.AXIS_ID_RE.match(ax):
            ctx.say("축 항목 ID 형식이 맞지 않아요.")
            return EXIT_USAGE
    if a.label is not None and not (1 <= len(a.label) <= 80):
        ctx.say("장치 이름은 1~80자예요.")
        return EXIT_USAGE
    account_label = None
    if getattr(a, "browser", False):
        r = browser_token(ctx, server, "device", client_name=a.label)
        if r is None:
            return EXIT_ERR
        token, account_label = r["token"], r.get("account_label")
    elif a.token_stdin:
        token = ctx.stdin.readline().strip()
    else:
        token = ctx.getpass_fn("업로드 토큰(화면에 안 보임): ").strip()
    try:
        stream_id, _tid = contract.parse_token(token)
    except contract.ContractError:
        ctx.say("토큰 형식이 맞지 않아요. 서버 연결 장치 화면의 토큰을 그대로 붙여 넣으세요.")
        return EXIT_USAGE
    stored = False
    if getattr(a, "browser", False):
        # 브라우저 로그인은 서버에 장치를 이미 만들었다 — 확인 전에 Keychain 에 먼저 둔다(고아 장치 방지).
        # 확인이 네트워크로 실패하면 남겨 두고 다음 run-once 가 확인을 마친다. 서버가 거절하면 지운다
        ctx.paths.ensure()
        try:
            ctx.keystore(_config.load(ctx.paths)).set(_config.token_account(stream_id), token)
        except keystore.KeyStoreError as e:
            ctx.say(f"자격 증명 저장소에 쓰지 못했어요: {e}. 평문으로 저장하지 않고 멈춥니다.")
            ctx.say("  서버엔 이 장치가 생겼어요 — 웹·대화에서 해제한 뒤 다시 하세요.")
            return EXIT_ERR
        _connect_pending(ctx, server, stream_id)
        stored = True
    # 1) 서버 확인 — 실패하면 아무것도 저장하지 않는다(브라우저 경로는 위 예외)
    try:
        info = _uploader(ctx, server, token).device()
    except DeviceError as e:
        if stored:
            return _connect_check_failed(ctx, e, stream_id)
        if e.kind == "auth":
            ctx.say(f"서버가 토큰을 받지 않았어요({e.code or e.status}). 연결 장치 화면에서 토큰을 다시 발급하세요.")
        elif e.kind == "network":
            ctx.say("서버에 닿지 못했어요. 주소·네트워크를 확인하세요.")
        else:
            ctx.say(f"서버 확인 실패: http-{e.status} {e.code}".rstrip())
        return EXIT_ERR
    return _finish_connect(ctx, server, token, stream_id, info, a, account_label)


CONNECT_PENDING_FILE = "connect-pending.json"   # {server_url, stream_id} — 브라우저 연결 확인 대기. 토큰 없음


def _connect_pending(ctx: Ctx, server, stream_id) -> None:
    """확인 대기 표식 쓰기(server·stream_id) · None 이면 지우기."""
    path = os.path.join(ctx.paths.home, CONNECT_PENDING_FILE)
    try:
        if server is None:
            if os.path.exists(path):
                os.remove(path)
        else:
            osutil.atomic_write(path, json.dumps({"server_url": server, "stream_id": stream_id}, sort_keys=True).encode())
    except OSError:
        pass


_STREAM_RE = re.compile(r"^is_[0-9a-f]{24}$")


def _read_connect_pending(ctx: Ctx):
    """확인 대기 표식 → (server, stream_id) | None(없음·깨짐 — 깨졌으면 지운다)."""
    path = os.path.join(ctx.paths.home, CONNECT_PENDING_FILE)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            m = json.load(f)
        server, sid = _config.check_server_url(m["server_url"]), m["stream_id"]
        if not isinstance(sid, str) or not _STREAM_RE.match(sid):
            raise ValueError("stream_id")
        return server, sid
    except (OSError, ValueError, KeyError, TypeError, _config.ConfigError):
        _connect_pending(ctx, None, None)
        return None


def _connect_check_failed(ctx: Ctx, e, stream_id) -> int:
    """미리 저장한 브라우저 토큰의 서버 확인 실패 — 거절이면 지우고, 네트워크·서버 오류면 남겨 둔다."""
    from .uploader import AUTH_CODES
    if e.kind == "auth" or e.code in AUTH_CODES:
        try:
            ctx.keystore(_config.load(ctx.paths)).delete(_config.token_account(stream_id))
        except (keystore.KeyStoreError, _config.ConfigError):
            pass
        _connect_pending(ctx, None, None)
        ctx.say(f"서버가 새 토큰을 받지 않아 지웠어요({e.code or e.status}). `connect --browser` 를 다시 하세요.")
    else:
        ctx.say("서버 확인을 마치지 못했어요(" + str(e) + "). 토큰은 Keychain 에 저장해 뒀어요(표시 안 함) — "
                "다음 `run-once` 때 확인을 마칩니다.")
    return EXIT_ERR


def resume_connect(ctx: Ctx) -> int | None:
    """브라우저 연결 확인 대기가 있으면 서버 확인을 마친다(run-once 시작 때). 대기가 없으면 None."""
    from .uploader import DeviceError
    pend = _read_connect_pending(ctx)
    if pend is None:
        return None
    server, stream_id = pend
    try:
        token = ctx.keystore(_config.load(ctx.paths)).get(_config.token_account(stream_id))
    except keystore.KeyStoreError as e:
        ctx.say(f"브라우저 연결 확인: 자격 증명 저장소 접근 불가: {e}")
        return EXIT_ERR
    if not token:
        _connect_pending(ctx, None, None)
        return None
    try:
        info = _uploader(ctx, server, token).device()
    except DeviceError as e:
        return _connect_check_failed(ctx, e, stream_id)
    return _finish_connect(ctx, server, token, stream_id, info, None, None)


def _finish_connect(ctx: Ctx, server, token, stream_id, info, a, account_label) -> int:
    """서버 확인(device) 뒤 — 설정 반영·Keychain 저장. a 가 None 이면 덮어쓰기 없음(run-once 의 연결 확인)."""
    ctx.paths.ensure()
    cfg = _config.load(ctx.paths)
    try:
        new = _config.apply_device_info(cfg, info, expected_stream=stream_id)
    except _config.ConfigError as e:
        ctx.say(f"서버 장치 정보가 맞지 않아요: {e}")
        pend = _read_connect_pending(ctx)
        if pend is not None and pend[1] == stream_id:     # 미리 저장한 브라우저 토큰만 지운다
            try:
                ctx.keystore(cfg).delete(_config.token_account(stream_id))
            except keystore.KeyStoreError:
                pass
            _connect_pending(ctx, None, None)
        return EXIT_ERR
    overrides = []
    a = a or argparse.Namespace(hmac_namespace=None, policy_revision=None, axis=[], label=None)
    if a.hmac_namespace is not None and a.hmac_namespace != new["hmac_namespace"]:
        new["hmac_namespace"] = a.hmac_namespace
        overrides.append("hmac_namespace")
    if a.policy_revision is not None and a.policy_revision != new["policy_revision"]:
        new["policy_revision"] = a.policy_revision
        overrides.append("policy_revision")
    if a.axis:
        new["allowed_axes"] = list(dict.fromkeys(a.axis))
        overrides.append("allowed_axes")
    if a.label is not None:
        new["device_label"] = a.label
    new["server_url"] = server
    # 2) 자격 증명 저장
    ks = ctx.keystore(cfg)
    old_sid = cfg.get("source_instance_id")
    try:
        ks.set(_config.token_account(stream_id), token)
        hk_acct = _config.hmac_account(new["hmac_namespace"])
        made_key = False
        if not ks.get(hk_acct):
            ks.set(hk_acct, hmacid.new_key_hex())
            made_key = True
        ks.delete(pending_token_account(stream_id))     # 새로 받은 토큰이 앞선 교체 대기분을 대신한다
        if old_sid and old_sid != stream_id:            # M3 계정(입력원) 전환 — 옛 계정 토큰은 이 PC 에서 지운다
            ks.delete(_config.token_account(old_sid))
            ks.delete(pending_token_account(old_sid))
    except keystore.KeyStoreError as e:
        ctx.say(f"자격 증명 저장소에 쓰지 못했어요: {e}. 평문으로 저장하지 않고 멈춥니다.")
        return EXIT_ERR
    try:
        _config.save(ctx.paths, new)
    except _config.ConfigError as e:
        ctx.say(f"설정 오류: {e}")
        return EXIT_ERR
    _set_rotate_refused(ctx, None, "", osutil.kst_now())   # 새 토큰 — 지난 교체 거절 기록은 의미 없다
    _connect_pending(ctx, None, None)
    ctx.say("연결했어요(서버 확인 완료).")
    if isinstance(account_label, str) and account_label:
        ctx.say(f"  계정: {account_label[:120]}")
    ctx.say(f"  입력원 ID: {stream_id}")
    ctx.say(f"  정책 판: {new['policy_revision']} · 허용 행동: {', '.join(new['allowed_actions'] or []) or '없음'}"
            f" · 허용 축 {len(new['allowed_axes'])}개")
    ctx.say(f"  토큰 만료: {new.get('token_expires_at') or '모름'}")
    ctx.say("  업로드 토큰: Keychain 에 저장(표시 안 함)")
    ctx.say("  HMAC 키: " + ("새로 만들어 Keychain 에 저장" if made_key else "기존 키 사용"))
    if overrides:
        ctx.say("  서버 값을 덮어씀: " + ", ".join(overrides))
    ctx.say(f"  설정 파일: {ctx.paths.config}")
    return EXIT_OK


def cmd_validate(ctx: Ctx, a) -> int:
    bad = 0
    try:
        cfg = _config.load(ctx.paths)
    except _config.ConfigError as e:
        ctx.say(f"설정 오류: {e}")
        return EXIT_ERR
    pol = _config.policy_of(cfg) if cfg.get("source_instance_id") else None
    targets = []
    if os.path.isdir(ctx.paths.pending):
        targets += [("pending/" + n, os.path.join(ctx.paths.pending, n))
                    for n in sorted(os.listdir(ctx.paths.pending)) if n.endswith(".json")]
    targets += [(f, f) for f in a.files]
    for label, path in targets:
        try:
            with open(path, "rb") as f:
                contract.validate_bytes(f.read(), policy=pol)
            ctx.say(f"OK   {os.path.basename(label)}")
        except contract.ContractError as e:
            bad += 1
            ctx.say(f"FAIL {os.path.basename(label)} {e.code} {e.field}")
        except OSError:
            bad += 1
            ctx.say(f"FAIL {os.path.basename(label)} UNREADABLE")
    ctx.say(f"설정 OK · 검사 {len(targets)}건 · 실패 {bad}건")
    return EXIT_OK if bad == 0 else EXIT_ERR


def cmd_run_once(ctx: Ctx, a) -> int:
    resume_connect(ctx)        # 브라우저 연결 확인 대기가 있으면 먼저 마친다(실패해도 이번 실행은 그대로)
    try:
        cfg = _config.load(ctx.paths)
    except _config.ConfigError as e:
        ctx.say(f"설정 오류: {e}")
        return EXIT_ERR
    if a.resume:
        st = _store.Store(ctx.paths)
        try:
            ok = st.clear_halt(a.resume)
        finally:
            st.close()
        ctx.say(f"멈춤 해제: {a.resume}" if ok else f"멈춤 없음: {a.resume}")
    ks = ctx.keystore(cfg)

    def summarizer(st, c):
        from . import summary
        return summary.summarize(st, c, paths=ctx.paths, exec_runner=ctx.exec_runner)

    from .adapters import AdapterError
    if not a.no_upload:
        # 지난 교체에서 확인 못 한 새 토큰이 있으면 먼저 확인·승격(M2 — 응답 유실·네트워크 끊김 복구)
        try:
            pr = _with_run_lock(ctx, lambda: promote_pending(ctx, cfg, ks))
        except keystore.KeyStoreError as e:
            ctx.say(f"실행 멈춤: 새 토큰을 자격 증명 저장소에 쓰지 못했어요: {e}")
            return EXIT_ERR
        if pr:
            ctx.say(_rotate_message(pr))
    try:
        res = runner.run_once(ctx.paths, ks=ks, uploader_factory=ctx.uploader_factory, summarizer=summarizer,
                              scheduled=a.scheduled, upload=not a.no_upload)
    except (runner.RunError, AdapterError, keystore.KeyStoreError, _config.ConfigError) as e:
        ctx.say(f"실행 멈춤: {e}")
        return EXIT_ERR
    except Exception as e:  # 요약 단계 설정 오류 등 — 값 없이 종류만
        ctx.say(f"실행 멈춤: {type(e).__name__}")
        return EXIT_ERR
    if res.get("skipped"):
        ctx.say("이미 실행 중이라 건너뛰었어요.")
        return EXIT_OK
    ctx.say(json.dumps({k: v for k, v in res.items()}, ensure_ascii=False, sort_keys=True))
    up = res.get("upload") or {}
    stopped = (up.get("stopped") or "").replace("-halted", "")
    if "upload" in res and stopped not in ("auth", "config") and not a.no_rotate:
        # 만료 30일 안이면 Bearer 교체(결정 0). 실패해도 이번 실행 결과(exit)는 바꾸지 않는다
        try:
            rcfg = _config.load(ctx.paths)
            rr = _with_run_lock(ctx, lambda: rotate_token(ctx, rcfg, ks))
        except (keystore.KeyStoreError, _config.ConfigError) as e:
            rr = None
            ctx.say(f"토큰 교체: 자격 증명 저장소·설정 오류로 건너뛰었어요({type(e).__name__}).")
        if rr:
            ctx.say(_rotate_message(rr))
    hints = {
        "auth": "서버가 토큰을 거절했어요. 웹 계정 메뉴 › 연결 장치에서 토큰을 다시 발급해 connect 한 뒤",
        "config": "입력원 ID 가 토큰과 달라요. connect 를 다시 한 뒤",
        "account": "웹에서 표시 이름을 먼저 정한 뒤",
        "policy": "장치 허용 규칙이 바뀌었는데 자동으로 다시 받지 못했어요(policy_refresh 참고). connect 를 다시 한 뒤",
        "forbidden": "서버가 요청을 막았어요. 연결 장치 화면을 확인한 뒤",
    }
    if stopped in hints:
        ctx.say(f"{hints[stopped]} `run-once --resume {stopped}` 로 다시 시작하세요.")
        return EXIT_HALT
    return EXIT_OK


def cmd_status(ctx: Ctx, a) -> int:
    try:
        cfg = _config.load(ctx.paths)
    except _config.ConfigError as e:
        ctx.say(f"설정 오류: {e}")
        return EXIT_ERR
    connected = bool(cfg.get("source_instance_id"))
    ctx.say(f"홈: {ctx.paths.home}")
    if os.path.exists(os.path.join(ctx.paths.home, CONNECT_PENDING_FILE)):
        ctx.say("브라우저 연결: 서버 확인 대기(다음 run-once 때 마침)")
    ctx.say(f"연결: {'예' if connected else '아니오'}" + (f" · 입력원 {cfg['source_instance_id']}" if connected else ""))
    if connected:
        try:
            ks = ctx.keystore(cfg)
            has_tok = bool(ks.get(_config.token_account(cfg["source_instance_id"])))
            has_key = bool(ks.get(_config.hmac_account(cfg["hmac_namespace"]))) if cfg.get("hmac_namespace") else False
            ctx.say(f"업로드 토큰: {'있음' if has_tok else '없음'} · HMAC 키: {'있음' if has_key else '없음'}")
            if ks.get(pending_token_account(cfg["source_instance_id"])):
                ctx.say("교체 대기 토큰: 있음(다음 run-once 때 확인)")
            ctx.say(f"토큰 만료: {cfg.get('token_expires_at') or '모름'} · 정책 판 {cfg.get('policy_revision')}")
        except keystore.KeyStoreError as e:
            ctx.say(f"자격 증명 저장소 접근 불가: {e}")
    en = [n for n, s in (cfg.get("adapters") or {}).items() if s.get("enabled")]
    ctx.say("켜진 어댑터: " + (", ".join(en) if en else "없음"))
    ctx.say("무인 요약: " + ("켜짐" if (cfg.get("summary") or {}).get("enabled") else "꺼짐"))
    if osutil.IS_MAC or osutil.IS_WINDOWS:
        try:
            is_installed = schedule.installed(ctx.launch_agents_dir, runner=ctx.schedule_runner)
            ctx.say("예약: " + ("등록됨" if is_installed else "없음"))
        except schedule.ScheduleError:
            ctx.say("예약: 확인 실패")
    if os.path.exists(ctx.paths.db):
        st = _store.Store(ctx.paths)
        try:
            c = st.counts()
            ctx.say(f"이벤트 {c['events']} · 대기 {c['pending']} · 접수 {c['accepted']} · 멈춤 {c['halted']} · "
                    f"충돌 {c['conflict']} · 거절 {c['rejected']} · 삭제됨 {c['deleted']} · 격리 {c['quarantined']} · 사람 {c['people']}")
            ctx.say(f"오늘 요약 시도: {st.summary_attempts_today(osutil.kst_today())}")
            if c["halts"]:
                ctx.say("멈춤 범위: " + ", ".join(c["halts"]))
        finally:
            st.close()
    return EXIT_OK


def cmd_configure_cli(ctx: Ctx, a) -> int:
    selected = None
    if not a.clear:
        selected = a.path
        if not selected or not os.path.isabs(selected) or not os.path.isfile(selected):
            ctx.say("CLI 경로는 설치된 실행 파일의 절대 경로여야 합니다.")
            return EXIT_ERR
        selected = os.path.realpath(selected)
        if not os.access(selected, os.X_OK) or (osutil.IS_WINDOWS and not selected.lower().endswith(".exe")):
            ctx.say("실행 가능한 CLI 파일을 선택해 주세요(Windows는 .exe).")
            return EXIT_ERR
    ctx.paths.ensure()
    try:
        with osutil.FileLock(ctx.paths.lock("config")):
            cfg = _config.load(ctx.paths)
            cfg["summary"]["cli_path"] = selected
            _config.save(ctx.paths, cfg)
    except osutil.LockBusy:
        ctx.say("다른 설정 저장이 진행 중입니다. 잠시 후 다시 시도해 주세요.")
        return EXIT_ERR
    ctx.say("CLI 경로를 지웠어요." if a.clear else "CLI 실행 파일 경로를 저장했어요.")
    return EXIT_OK


def cmd_configure_codex(ctx: Ctx, a) -> int:
    path = a.path
    models = a.model
    if (not isinstance(path, str) or not path or not os.path.isabs(path) or len(path) > 4096
            or "\x00" in path):
        ctx.say("Codex 실행 파일 절대 경로를 확인해 주세요.")
        return EXIT_ERR
    selected = os.path.realpath(path)
    if not os.path.isfile(selected) or not os.access(selected, os.X_OK):
        ctx.say("실행 가능한 Codex 파일을 선택해 주세요.")
        return EXIT_ERR
    if (not isinstance(models, list) or not 1 <= len(models) <= 20
            or len(set(models)) != len(models)
            or any(not isinstance(model, str)
                   or not re.fullmatch(r"[A-Za-z0-9._:/+-]{1,120}", model) for model in models)):
        ctx.say("Codex 모델 ID를 1개 이상, 서로 다르게 입력해 주세요.")
        return EXIT_ERR
    ctx.paths.ensure()
    try:
        with osutil.FileLock(ctx.paths.lock("config")):
            cfg = _config.load(ctx.paths)
            cfg["summary"]["codex_cli_path"] = selected
            cfg["summary"]["codex_models"] = list(models)
            _config.save(ctx.paths, cfg)
    except osutil.LockBusy:
        ctx.say("다른 설정 저장이 진행 중입니다. 잠시 후 다시 시도해 주세요.")
        return EXIT_ERR
    except _config.ConfigError:
        ctx.say("Codex 설정을 저장하지 못했습니다.")
        return EXIT_ERR
    # Setting a path/model list does not enable the provider readiness gate.
    ctx.say("Codex CLI와 모델 ID를 저장했어요.")
    return EXIT_OK


def cmd_schedule(ctx: Ctx, a) -> int:
    try:
        if a.action == "install":
            r = schedule.install(home=ctx.paths.home, launch_agents_dir=ctx.launch_agents_dir,
                                 runner=ctx.schedule_runner)
            ctx.say({"installed": "예약을 등록했어요(1시간마다).", "unchanged": "이미 같은 예약이 있어요."}[r])
        else:
            r = schedule.remove(launch_agents_dir=ctx.launch_agents_dir, runner=ctx.schedule_runner)
            ctx.say({"removed": "예약을 해제했어요. 원문·대응표는 그대로예요.", "absent": "등록된 예약이 없어요."}[r])
    except schedule.ScheduleError as e:
        ctx.say(f"예약 실패: {e}")
        return EXIT_ERR
    return EXIT_OK


def cmd_serve(ctx: Ctx, a, *, serve_forever=True):
    if getattr(a, "jobs", False):
        return cmd_serve_jobs(ctx, a)
    from . import viewer
    cfg = _config.load(ctx.paths)
    port = a.port if a.port is not None else cfg["viewer_port"]
    srv = viewer.make_server(port=port, resolve_raw=viewer.store_resolver(ctx.paths))
    ctx.say(f"원문 뷰어: http://{viewer.BIND_HOST}:{srv.server_address[1]}/raw/<id> (Ctrl+C 로 종료)")
    if not serve_forever:
        return srv
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
    return EXIT_OK


def cmd_serve_jobs(ctx: Ctx, a) -> int:
    """작업 실행 상주(③-0.1). 잠금 → 장치 인증 → 롱폴·실행. 출력 = 코드만 담은 JSON 줄(jobs._log_line) — 본문·토큰·주소·예외 메시지 없음.
    exit: 신호로 멈춤 0 · 설정·잠금 충돌·기타 1 · 인증(토큰 없음·거절·폐기) 3."""
    from . import jobs
    from .uploader import AUTH_CODES, DeviceError

    def log(line: str) -> None:
        ctx.say(line)
        flush = getattr(ctx.out, "flush", None)
        if flush:
            flush()

    def stop(why: str, err=None, code=EXIT_ERR) -> int:
        log(jobs._log_line({"event": "start", "stopped": why, "error": type(err).__name__ if err else None}))
        return code

    try:
        cfg = _config.load(ctx.paths)
    except _config.ConfigError as e:
        return stop("config", e)
    sid, server = cfg.get("source_instance_id"), cfg.get("server_url")
    if not sid or not server:
        return stop("not-connected")
    ctx.paths.ensure()
    try:
        token = ctx.keystore(cfg).get(_config.token_account(sid))
    except keystore.KeyStoreError as e:
        return stop("keystore", e)
    if not token:
        return stop("auth", code=EXIT_HALT)
    runner = jobs.GroupRunner()
    try:
        if ctx.jobs_adapter_factory:
            adapter = ctx.jobs_adapter_factory(runner)
        else:   # 실 CLI — MYCRM_JOBS_ALLOW_REAL_CLI=1 이 없으면 JobsError(약관 확인 전)
            cli_path = (cfg.get("summary") or {}).get("cli_path")
            adapter = jobs.ClaudeAdapter([cli_path] if cli_path else [], exec_runner=runner, paths=ctx.paths)
    except jobs.JobsError as e:
        return stop("adapter", e)

    def authenticate() -> str:
        try:
            info = _uploader(ctx, server, token).device()
        except DeviceError as e:
            if e.kind == "auth" or e.code in AUTH_CODES:
                return "auth"
            if e.kind == "network" or e.status == 429 or (e.status or 0) >= 500:
                return "network"
            return "error"
        return "ok" if isinstance(info, dict) and info.get("stream_id") == sid else "error"

    def make_worker(stopping, abort):
        client = (ctx.jobs_client_factory or jobs.Client)(server, token)
        return jobs.Worker(client, adapter, jobs.JsonState.for_paths(ctx.paths), sleep=lambda s: abort.wait(s),
                           stopping=stopping, abort=abort)

    try:
        res = jobs.serve_jobs(lock_path=ctx.paths.lock("jobs"), authenticate=authenticate, make_worker=make_worker,
                              runner=runner, log=log, **ctx.jobs_serve_kw)
    except jobs.JobsError as e:   # 깨진 jobs-state 등 — 고치지 않고 멈춘다
        return stop("state", e)
    s = res["stopped"]
    if s in ("signal", "worker-exit"):
        return EXIT_OK
    if s in ("auth", "auth-halted"):
        return EXIT_HALT
    return EXIT_ERR


def cmd_chat(ctx: Ctx, a) -> int:
    """웹 「대화」 상주. 장치 토큰(connect 로 넣은 것) → WebSocket → 턴 실행. 출력 = 코드만 담은 JSON 줄(본문·토큰·주소 없음).
    PR 1 은 --fake(FakeProvider)만 — 실 CLI(ClaudeProvider)는 PR 2. exit: 신호로 멈춤 0 · 설정·키 저장소 1 · 쓰는 법 2 · 인증 거절 3."""
    def log(rec: dict) -> None:
        keep = {k: v for k, v in rec.items() if k in ("event", "ok", "error", "status", "why", "end", "stopped")
                and (v is None or isinstance(v, (bool, int)) or (isinstance(v, str) and re.match(r"^[A-Za-z0-9_.-]{1,40}$", v)))}
        ctx.say(json.dumps(keep, sort_keys=True))
        flush = getattr(ctx.out, "flush", None)
        if flush:
            flush()

    if a.consent_only:
        if not (os.environ.get("MYCRM_CHAT_BRIDGE_SOCKET") and os.environ.get("MYCRM_CHAT_BRIDGE_TOKEN")):
            log({"event": "start", "stopped": "bridge"})
            return EXIT_ERR
    elif CHAT_CLAUDE_PROVIDER_READY and not a.fake:
        if not (os.environ.get("MYCRM_CHAT_BRIDGE_SOCKET") and os.environ.get("MYCRM_CHAT_BRIDGE_TOKEN")):
            log({"event": "start", "stopped": "bridge"})
            return EXIT_ERR
    try:
        cfg = _config.load(ctx.paths)
    except _config.ConfigError:
        log({"event": "start", "stopped": "config"})
        return EXIT_ERR
    sid, server = cfg.get("source_instance_id"), cfg.get("server_url")
    if not sid or not server:
        log({"event": "start", "stopped": "not-connected"})
        return EXIT_ERR
    try:
        token = ctx.keystore(cfg).get(_config.token_account(sid))
    except keystore.KeyStoreError:
        log({"event": "start", "stopped": "keystore"})
        return EXIT_ERR
    if not token:
        log({"event": "start", "stopped": "auth"})
        return EXIT_HALT
    # J-F7: one resident chat per home. A chat left by an earlier app run (its desktop died first) is ended here,
    # by the lock holder's pid only (agent/chat_instance.py). The lock is released in the finally below.
    from .chat_instance import ChatInstance, InstanceUnavailable
    instance = ctx.chat_kw.get("instance") or ChatInstance(ctx.paths.locks)
    try:
        instance.claim()
    except (InstanceUnavailable, OSError):
        log({"event": "start", "stopped": "instance"})
        return EXIT_ERR
    if instance.reaped is not None:
        log({"event": "start", "why": "reaped-previous"})
    try:
        return _run_chat(ctx, a, cfg, sid, server, log)
    finally:
        instance.release()


def _run_chat(ctx: Ctx, a, cfg, sid, server, log) -> int:
    import signal
    import threading
    from . import chat, chat_providers
    kw = dict(ctx.chat_kw)
    kw.pop("instance", None)
    if a.consent_only:
        from .consent_bridge import request_approval
        bridge_socket = os.environ["MYCRM_CHAT_BRIDGE_SOCKET"]
        bridge_token = os.environ["MYCRM_CHAT_BRIDGE_TOKEN"]
        provider = None
        kw.pop("provider", None)
        kw.pop("registry", None)

        def consent_request(request_id, authorization):
            return request_approval(bridge_socket, bridge_token, request_id, authorization)
    else:
        provider = kw.pop("provider", None) or (chat.FakeProvider() if a.fake else None)
        consent_request = kw.pop("consent_request", None)
        if consent_request is None and not a.fake:
            bridge_socket = os.environ.get("MYCRM_CHAT_BRIDGE_SOCKET")
            bridge_token = os.environ.get("MYCRM_CHAT_BRIDGE_TOKEN")
            if bridge_socket and bridge_token:
                from .consent_bridge import request_approval
                consent_request = lambda request_id, authorization: request_approval(
                    bridge_socket, bridge_token, request_id, authorization)
    claude_factory = kw.pop("claude_factory", None) if not (a.fake or a.consent_only) else None
    if a.fake or a.consent_only:
        kw.pop("claude_factory", None)
    codex_factory = kw.pop("codex_factory", None) if not (a.fake or a.consent_only) else None
    if a.fake or a.consent_only or not CHAT_CODEX_PROVIDER_READY:
        codex_factory = None
        kw.pop("codex_factory", None)
    stopping = kw.pop("stopping", None) or threading.Event()
    if os.environ.get("MYCRM_DESKTOP_CONTROL") == "1":
        def read_desktop_control():
            # Supervisor owns this pipe and sends one small stop record before
            # closing it. Read it only in desktop-managed mode so an interactive
            # terminal's stdin is never consumed by the resident chat process.
            while not stopping.is_set():
                try:
                    line = ctx.stdin.readline(1025)
                except TypeError:
                    line = ctx.stdin.readline()
                except Exception:
                    stopping.set()   # the desktop end of the pipe is gone
                    return
                if not line:
                    # EOF: the desktop app closed the pipe without a stop record (it crashed, was killed or quit
                    # abruptly). Stop like a stop record, so the CLI group ends and no chat is left behind (J-F7).
                    stopping.set()
                    return
                if len(line) > 1024:
                    continue
                try:
                    message = json.loads(line)
                except (TypeError, ValueError):
                    continue
                if isinstance(message, dict) and message == {"command": "stop"}:
                    stopping.set()
                    return

        threading.Thread(target=read_desktop_control, name="chat-desktop-control", daemon=True).start()
    old = {}
    if threading.current_thread() is threading.main_thread():
        for sig in (signal.SIGINT, signal.SIGTERM):
            old[sig] = signal.signal(sig, lambda *_: stopping.set())
    try:
        ks = ctx.keystore(cfg)

        def token_now():   # 매번 다시 읽는다 — run-once 의 rotate·웹 재발급 뒤에도 상주가 새 토큰으로 이어 간다
            try:
                return ks.get(_config.token_account(sid))
            except keystore.KeyStoreError:
                return None

        ref_store = kw.pop("ref_store", None) or chat_providers.CliSessionRefStore(ks, sid)
        live = not a.fake and not a.consent_only
        summary = cfg.get("summary") or {}
        if live and claude_factory is None and CHAT_CLAUDE_PROVIDER_READY:
            cli_path = summary.get("cli_path")
            if not cli_path:
                # J-F1: the person chose Codex only (or nothing yet). Advertise no Claude model and keep running, so
                # the other AI service and the consent relay still work; the PC app's first screen asks for the CLI.
                log({"event": "start", "why": "claude-not-configured"})
            else:
                from .chat_launch_authority import LaunchAuthorizationClient
                from .chat_claude import ClaudeProviderFactory, ClaudeProviderUnavailable
                try:
                    auth_client = LaunchAuthorizationClient(server, token_now)
                    # The factory resolves and pins the CLI and asks it for models once per start.
                    claude_factory = ClaudeProviderFactory(auth_client, cli_path=cli_path, server_url=server,
                        agent_home=ctx.paths.home, expected_device_id=sid)
                except ClaudeProviderUnavailable as exc:
                    if str(exc) != "models-unavailable":
                        log({"event": "start", "stopped": "claude-runtime"})
                        return EXIT_ERR
                    # No model list from the CLI: advertise no Claude model, keep the agent running.
                    claude_factory = None
                    log({"event": "start", "claude": "models-unavailable"})
                except Exception:
                    log({"event": "start", "stopped": "claude-runtime"})
                    return EXIT_ERR
        if live and codex_factory is None and CHAT_CODEX_PROVIDER_READY:
            cli_path = summary.get("codex_cli_path")
            models = summary.get("codex_models")
            if not (isinstance(cli_path, str) and isinstance(models, list) and models):
                # J-F1: Codex not chosen on this PC. Advertise no Codex model and keep running (see Claude above).
                log({"event": "start", "why": "codex-not-configured"})
            else:
                from .chat_launch_authority import LaunchAuthorizationClient
                from .chat_codex import CodexProviderFactory
                try:
                    auth_client = LaunchAuthorizationClient(server, token_now)
                    codex_factory = CodexProviderFactory(auth_client, cli_path=cli_path, server_url=server,
                        agent_home=ctx.paths.home, expected_device_id=sid, models=tuple(models))
                except Exception:
                    log({"event": "start", "stopped": "codex-runtime"})
                    return EXIT_ERR
        agent = chat.ChatAgent(chat.ws_url(server), token_now, provider, ref_store=ref_store,
                               agent_version=AGENT_VERSION, stopping=stopping, log=log, consent_request=consent_request,
                               claude_factory=claude_factory, codex_factory=codex_factory, **kw)
        why = agent.run()
    finally:
        for sig, h in old.items():
            signal.signal(sig, h)
    log({"event": "stop", "stopped": why})
    return EXIT_HALT if why == "auth" else EXIT_OK


def cmd_chat_mcp_bridge(ctx: Ctx, a) -> int:
    """Internal stdio MCP bridge entry used by the supervised agent sidecar."""
    argv = ["--agent-home", a.agent_home, "--session-id", a.session_id, "--turn-id", a.turn_id,
            "--device-id", a.device_id, "--provider", a.provider, "--model", a.model,
            "--authorization-path", a.authorization_path]
    # The provider factory pins this explicit home. Do not let the process-wide
    # --home/default context silently redirect bridge keystore/config lookup.
    return chat_mcp_bridge.main(argv, home=a.agent_home)


def cmd_disconnect(ctx: Ctx, a) -> int:
    """서버 토큰 폐기(POST /api/imports/device/revoke)와 로컬 자격 증명 제거를 나눠 결과를 보인다.
    서버 폐기가 네트워크·서버 오류로 실패하면 로컬 토큰을 남기고 멈춘다(다시 시도 가능). --local-only 는 서버를 건너뛴다."""
    from .uploader import DeviceError
    cfg = _config.load(ctx.paths)
    sid = cfg.get("source_instance_id")
    if not sid:
        ctx.say("연결된 입력원이 없어요.")
        return EXIT_OK
    ks = ctx.keystore(cfg)
    try:
        token = ks.get(_config.token_account(sid))
    except keystore.KeyStoreError as e:
        ctx.say(f"자격 증명 저장소 접근 불가: {e}")
        return EXIT_ERR
    if a.local_only or not token or not cfg.get("server_url"):
        server_msg = "건너뜀 — 웹 계정 메뉴 › 연결 장치에서 이 장치를 폐기하세요."
    else:
        try:
            r = _uploader(ctx, cfg["server_url"], token).revoke()
            if r.get("revoked") is not True or r.get("stream_id") != sid:
                raise DeviceError("server", 200, "UNEXPECTED")
            server_msg = "폐기함"
        except DeviceError as e:
            if e.kind == "auth":
                server_msg = f"이미 무효({e.code or 'http-401'}) — 폐기·만료된 토큰"
            else:
                ctx.say("서버 토큰: 폐기 못 함(" + str(e) + "). 로컬 토큰은 그대로 두었어요.")
                ctx.say("다시 시도하거나, 웹에서 폐기한 뒤 `disconnect --local-only` 를 쓰세요.")
                return EXIT_ERR
    try:
        removed = ks.delete(_config.token_account(sid))
        ks.delete(pending_token_account(sid))
        key_removed = None
        if a.forget_hmac_key and cfg.get("hmac_namespace"):
            key_removed = ks.delete(_config.hmac_account(cfg["hmac_namespace"]))
    except keystore.KeyStoreError as e:
        ctx.say(f"서버 토큰: {server_msg}")
        ctx.say(f"자격 증명 저장소 접근 불가: {e}")
        return EXIT_ERR
    cfg.update({"source_instance_id": None, "token_expires_at": None})
    _config.save(ctx.paths, cfg)
    ctx.say(f"서버 토큰: {server_msg}")
    ctx.say("로컬 업로드 토큰: " + ("제거함" if removed else "없었음"))
    if key_removed is not None:
        ctx.say("HMAC 키: " + ("제거함(같은 사람 연결이 끊김)" if key_removed else "없었음"))
    else:
        ctx.say("HMAC 키: 유지(같은 사람 연결용)")
    ctx.say("예약·원문·대응표: 그대로(예약 해제는 `schedule remove`).")
    return EXIT_OK


def cmd_migrate(ctx: Ctx, a) -> int:
    """실자료 이관 업로더 — agent/migrate.py(설치 패키지 목록 packaging/agent-files.json 에 있다. 앱 sidecar 가
    `migrate login --token-stdin` 을 돌린다). 목록에서 빠진 빌드면 ImportError 안내."""
    try:
        from . import migrate
    except ImportError:
        ctx.say("이 명령은 설치 패키지에 없어요. 키트 루트에서 파이썬으로 실행하세요: python3 -m agent migrate …")
        return EXIT_USAGE
    return migrate.run(ctx, a)


COMMANDS = {"connect": cmd_connect, "validate": cmd_validate, "run-once": cmd_run_once, "status": cmd_status,
            "schedule": cmd_schedule, "serve": cmd_serve, "disconnect": cmd_disconnect,
            "configure-cli": cmd_configure_cli, "configure-codex": cmd_configure_codex,
            "migrate": cmd_migrate, "chat": cmd_chat,
            "chat-mcp-bridge": cmd_chat_mcp_bridge}


def _utf8_stdio():
    # Windows 콘솔·파이프는 기본 cp1252 라 한국어 출력이 UnicodeEncodeError 로 죽는다.
    for stream in (sys.stdout, sys.stderr):
        try:
            if hasattr(stream, "reconfigure") and codecs.lookup(stream.encoding or "ascii").name != "utf-8":
                stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def main(argv=None, **ctx_kw) -> int:
    _utf8_stdio()
    p = _parser()
    a = p.parse_args(argv)
    if not a.cmd:
        p.print_help()
        return EXIT_USAGE
    ctx = Ctx(a.home or _config.default_home(), **ctx_kw)
    try:
        return COMMANDS[a.cmd](ctx, a)
    except _config.ConfigError as e:
        ctx.say(f"설정 오류: {e}")
        return EXIT_ERR


if __name__ == "__main__":
    sys.exit(main())
