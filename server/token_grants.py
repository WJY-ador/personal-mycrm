"""PC 연결·토큰 대화 발급(2026-11-02 가안 2 「상주 앱 수령형」) — 설치본 · grant 상태기계 · 앱 세션 수령 · 자동 연결 · 교체.

정본: notes/2026-11-02_pc-connect-구현계획.md §0·§2~§4(고정본) · raw 「최종판」 G·I·J.

한계(§0): 서버는 사용자 발화를 확인할 수 없다. 토큰 수령의 실제 관문 = 앱 세션 바인딩(같은 계정 로그인 세션 + X-MyCRM-Desktop 헤더 —
web.py 가 검사한다). 대화 쪽 가드는 규칙 문장·한도·D(bind)뿐. prompt injection 으로 pc_connect(W)가 불리면 사람 동작 없이 내 앱이
내 장치 토큰을 받을 수 있다 — 피해 상한 = 내 PC 에 내 장치 토큰(사용자 데이터 읽기 없음, 수집은 run-once 때만). 이관은 D(bind).

  waiting ─(앱 redeem: 계정·설치본·미사용·미만료·scope 검사 → 그 자리에서 토큰 발급)→ delivered
     ├─(10분)→ expired      └─(pc_forget)→ cancelled

· 토큰 값은 redeem·auto·rotate 응답에만 있다. grant 표·MCP 응답·오류·preview·감사·로그에는 없다(감사 = grant id·scope·via·장치 이름·시각).
· M2: 장치 토큰은 imports.pending_in(대기 토큰), 이관 토큰은 migration.token_issue_in — 옛 토큰은 새 토큰 첫 사용 때 무효.
· 호출하는 곳: main.py(MCP facade 「PC 연결」 op 7 — 직접 도구 없음) · web.py(/desktop/* 5 · /api/device/rotate) · imports.expire_pending(정리 회차).
오류 = db.CrmError(code, message, action[, detail]). HTTP 상태는 http_status(code).
"""
from __future__ import annotations

import datetime as _dt
import re
import secrets

import db
import imports
import migration
from db import CrmError, _all, _one, tx

GRANT_MINUTES = 10          # grant 대기 시간
ACTIVE_SECONDS = 120        # 「켜진 앱」 = 최근 2분 안에 폴링한 설치본
POLL_SECONDS = 30           # 앱 폴링 간격(응답으로 알려 준다)
OPEN_MAX = 3                # 계정당 열린(대기·미만료) grant
DAILY_MAX = 10              # 계정당 하루(KST) grant
INSTALL_MAX = 10            # 계정당 해제 안 된 설치본
SESSION_PER_MIN = 10        # auto·rotate(세션) 계정당 분당
IDLE_ROTATE_DAYS = 90       # 이 기간 업로드가 없던 장치는 Bearer 교체 거절(보조 규칙)
KEEP_DAYS = 30              # 끝난 grant 행 보관(정리 회차가 지운다)
OS_VALUES = ("darwin", "win32", "linux")
SCOPES = ("device", "migration")
VIA = "mcp"

_INST_RE = re.compile(r"^di_[0-9a-f]{24}$")
_GRANT_RE = re.compile(r"^tg_[0-9a-f]{24}$")

_HTTP = {"UNAUTHORIZED": 401, "NOT-OWNER": 403, "INSTALLATION-UNKNOWN": 404, "NOT-FOUND": 404, "GRANT-USED": 409, "GRANT-EXPIRED": 410,
         "DEVICE-REVOKED": 409, "DEVICE-LIMIT": 409, "NAME-REQUIRED": 403, "MIGRATION-NOT-ALLOWED": 403, "MIGRATION-OFF": 503,
         "RATE-LIMIT": 429, "ARG-INVALID": 400, "PAYLOAD-LIMIT": 413, "NO-ACTIVE-APP": 409, "QUOTA-GLOBAL": 507,
         "HANDOFF-INVALID": 400, "ORIGIN": 403}


def http_status(code: str) -> int:
    """CrmError code → HTTP 상태(/desktop/* · /api/device/rotate). 모르는 code 는 imports.http_status."""
    return _HTTP.get(code) or imports.http_status(code)


def _err(code, msg, action="", **detail):
    e = CrmError(code, msg, action)
    if detail:
        e.detail = detail
    return e


def _iso(v):
    return v.isoformat() if isinstance(v, (_dt.datetime, _dt.date)) else v


def _inst_id(v) -> str:
    v = v if isinstance(v, str) else ""
    if not _INST_RE.match(v):
        raise _err("ARG-INVALID", "installation_id 는 di_ 로 시작하는 설치본 ID 예요.", "pc_list 로 ID 를 확인하세요.")
    return v


def _client(name, os_) -> tuple:
    name = db._label(name, "PC 이름")
    if os_ not in OS_VALUES:
        raise _err("ARG-INVALID", f"os 는 {', '.join(OS_VALUES)} 중 하나예요.")
    return name, os_


# ── 설치본 ─────────────────────────────────────────────
_INST_COLS = ("id,client_name,os,device_id,created_at,last_login_at,last_seen_at,revoked_at,"
              f"(last_seen_at >= now() - make_interval(secs => {ACTIVE_SECONDS})) AS active")


def _inst(c, uid, iid, lock=False) -> dict:
    """내 설치본 행. 다른 계정 것 = NOT-OWNER(M3) · 없음 = INSTALLATION-UNKNOWN."""
    iid = _inst_id(iid)
    r = _one(c, f"SELECT {_INST_COLS} FROM desktop_installations WHERE user_id=%s AND id=%s" + (" FOR NO KEY UPDATE" if lock else ""),
             (uid, iid))
    if r:
        return r
    if _one(c, "SELECT 1 AS x FROM desktop_installations WHERE id=%s", (iid,)):
        raise _err("NOT-OWNER", "다른 계정에 등록된 PC 예요.", "앱에서 지금 계정으로 다시 등록하세요(옛 계정 장치 토큰은 지운다).")
    raise _err("INSTALLATION-UNKNOWN", "등록되지 않은 PC 예요.", "앱에서 다시 등록하세요(installation_id 없이).")


def _device(c, uid, did, lock=False):
    if not did:
        return None
    return _one(c, "SELECT id,label,revoked_at,token_expires_at,last_used_at,created_at FROM import_streams WHERE user_id=%s AND id=%s "
                   "AND channel='device'" + (" FOR NO KEY UPDATE" if lock else ""), (uid, did))


def _dev_brief(d):
    return {"device_id": d["id"], "label": d["label"], "active": d["revoked_at"] is None} if d else None


def _inst_out(c, uid, r) -> dict:
    return {"installation_id": r["id"], "client_name": r["client_name"], "os": r["os"], "revoked": r["revoked_at"] is not None,
            "device": _dev_brief(_device(c, uid, r["device_id"]))}


def _account(c, uid) -> str:
    return _one(c, "SELECT email FROM users WHERE id=%s", (uid,))["email"]


def installation_register(uid: str, client_name, os_, installation_id=None) -> dict:
    """POST /desktop/installations — 앱 로그인 직후 upsert. id 없음 = 새로(계정당 해제 안 된 것 INSTALL_MAX), 내 id = 이름·OS 갱신 +
    last_login_at·last_seen_at = 지금(해제 기록은 그대로), 다른 계정 id = NOT-OWNER, 모르는 id = INSTALLATION-UNKNOWN.
    반환 {installation_id, client_name, os, revoked, device, account_label, poll_seconds}."""
    name, os_ = _client(client_name, os_)
    with tx() as c:
        db._user_lock(c, uid)
        if installation_id not in (None, ""):
            r = _inst(c, uid, installation_id, lock=True)
            c.execute("UPDATE desktop_installations SET client_name=%s, os=%s, last_login_at=now(), last_seen_at=now() "
                      "WHERE user_id=%s AND id=%s", (name, os_, uid, r["id"]))
            iid = r["id"]
        else:
            n = _one(c, "SELECT count(*) AS n FROM desktop_installations WHERE user_id=%s AND revoked_at IS NULL", (uid,))["n"]
            if n >= INSTALL_MAX:
                raise _err("RATE-LIMIT", f"등록한 PC 가 {INSTALL_MAX}대예요.", "쓰지 않는 PC 를 대화에서 연결 해제(pc_forget)한 뒤 다시 하세요.")
            iid = "di_" + secrets.token_hex(12)
            c.execute("INSERT INTO desktop_installations (user_id,id,client_name,os) VALUES (%s,%s,%s,%s)", (uid, iid, name, os_))
        r = _inst(c, uid, iid)
        return {**_inst_out(c, uid, r), "account_label": _account(c, uid), "poll_seconds": POLL_SECONDS}


def grants_poll(uid: str, installation_id) -> dict:
    """GET /desktop/grants — 이 설치본 앞 대기(미만료) grant 목록 + 설치본 상태. last_seen_at 갱신(지목 규칙). 해제된 설치본도 폴링한다."""
    with tx() as c:
        r = _inst(c, uid, installation_id)
        c.execute("UPDATE desktop_installations SET last_seen_at=now() WHERE user_id=%s AND id=%s", (uid, r["id"]))
        rows = _all(c, "SELECT id,scope,expires_at FROM token_grants WHERE user_id=%s AND installation_id=%s AND state='waiting' "
                       "AND expires_at > now() ORDER BY created_at", (uid, r["id"]))
        return {"installation": _inst_out(c, uid, r),
                "grants": [{"grant_id": g["id"], "scope": g["scope"], "expires_at": _iso(g["expires_at"])} for g in rows],
                "poll_seconds": POLL_SECONDS}


# ── 장치 토큰 발급(설치본 기준) ─────────────────────────────

def _device_token(c, uid, inst, *, allow_new: bool, revive: bool, via: str) -> dict:
    """설치본의 장치 토큰 — 살아 있는 장치면 대기 토큰(M2), 없으면(allow_new) 새 장치 + 연결. revive=False 면 해제 기록을 지킨다
    (설치본 해제·장치 해제 = DEVICE-REVOKED). revive=True(대화 pc_connect 수령) 면 해제를 풀고 새 장치. 반환 {token, device, created, token_expires_at}."""
    if inst["revoked_at"] is not None and not revive:
        raise _err("DEVICE-REVOKED", "이 PC 연결은 해제됐어요.", "대화에서 「PC 다시 연결해 줘」라고 하면 다시 연결돼요.")
    dev = _device(c, uid, inst["device_id"], lock=True)
    if dev is not None and dev["revoked_at"] is None:
        token, exp = imports.pending_in(c, uid, dev["id"])
        created = False
    elif dev is not None and not revive:
        raise _err("DEVICE-REVOKED", "이 PC 의 연결 장치는 해제됐어요.", "대화에서 「PC 다시 연결해 줘」라고 하면 다시 연결돼요.")
    elif not allow_new:
        raise _err("NOT-FOUND", "이 PC 에 연결된 장치가 없어요.", "앱에서 수집을 켜면 자동으로 연결돼요.")
    else:
        out = imports.connect_in(c, uid, inst["client_name"], via=via)
        dev = _device(c, uid, out["device"]["id"])
        token, exp, created = out["token"], dev["token_expires_at"], True
    c.execute("UPDATE desktop_installations SET device_id=%s, revoked_at=NULL WHERE user_id=%s AND id=%s", (dev["id"], uid, inst["id"]))
    return {"token": token, "device": dev, "created": created, "token_expires_at": _iso(exp)}


def _session_rate(c, uid):
    if imports._bump(c, uid, "desktop", "minute", "request")["n"] > SESSION_PER_MIN:
        raise _err("RATE-LIMIT", f"요청이 너무 잦아요(분당 {SESSION_PER_MIN}회).", "1분 뒤 다시 하세요.")


def _rate(uid):
    with tx() as c:   # 별도 트랜잭션 — 뒤에서 실패해도 센다
        _session_rate(c, uid)


def device_auto(uid: str, installation_id, client_name=None, os_=None) -> dict:
    """POST /desktop/device/auto — 수집을 처음 켤 때(앱 [동기화] 첫 클릭·예약 켬) 이 PC 에 장치 토큰이 없으면. 살아 있는 장치 = 대기 토큰
    (토큰 분실 재발급, created=false) · 없으면 새 장치(created=true). 해제한 PC·장치는 DEVICE-REVOKED(자동으로 다시 붙지 않는다).
    표시 이름 관문(NAME-REQUIRED)·전역 크기는 web 이 db.write_gate("device_connect") 로 먼저 본다.
    반환 {token, device_id, device_label, account_label, token_expires_at, created}. 감사 device_connect(via=desktop) 또는 device_rotate."""
    _rate(uid)
    with tx() as c:
        db._user_lock(c, uid)
        inst = _inst(c, uid, installation_id, lock=True)
        if client_name is not None or os_ is not None:
            name, os2 = _client(client_name if client_name is not None else inst["client_name"], os_ if os_ is not None else inst["os"])
            c.execute("UPDATE desktop_installations SET client_name=%s, os=%s WHERE user_id=%s AND id=%s", (name, os2, uid, inst["id"]))
            inst = _inst(c, uid, inst["id"])
        out = _device_token(c, uid, inst, allow_new=True, revive=False, via="desktop")
        if not out["created"]:
            db._audit(c, "device_rotate", uid, uid, {"device_id": out["device"]["id"], "via": "desktop_auto", "result": "ok"})
        return {"token": out["token"], "device_id": out["device"]["id"], "device_label": out["device"]["label"],
                "account_label": _account(c, uid), "token_expires_at": out["token_expires_at"], "created": out["created"]}


def device_rotate_session(uid: str, installation_id) -> dict:
    """POST /desktop/device/rotate — 앱 main 자동 교체(세션). 대기 토큰(M2). 장치 없음 = NOT-FOUND(→ auto) · 해제 = DEVICE-REVOKED.
    반환 {token, device_id, device_label, account_label, token_expires_at}. 감사 device_rotate(via=desktop)."""
    _rate(uid)
    with tx() as c:
        db._user_lock(c, uid)
        inst = _inst(c, uid, installation_id, lock=True)
        out = _device_token(c, uid, inst, allow_new=False, revive=False, via="desktop")
        db._audit(c, "device_rotate", uid, uid, {"device_id": out["device"]["id"], "via": "desktop", "result": "ok"})
        return {"token": out["token"], "device_id": out["device"]["id"], "device_label": out["device"]["label"],
                "account_label": _account(c, uid), "token_expires_at": out["token_expires_at"]}


def device_rotate_bearer(authorization: str) -> dict:
    """POST /api/device/rotate — Bearer 장치 토큰(CLI·uploader)으로 자기 장치 토큰 교체. 대기 토큰(M2) — 옛 토큰은 새 토큰 첫 사용 때 무효.
    상한 없음. 보조 규칙: IDLE_ROTATE_DAYS 동안 업로드가 없던 장치는 TOKEN-EXPIRED(다시 연결). 반환 {token, stream_id, token_expires_at}.
    감사 device_rotate(via=bearer)."""
    dev = imports.authenticate(authorization)
    imports._rate(dev)
    uid = dev["user_id"]
    with tx() as c:
        db._user_lock(c, uid)
        r = _one(c, "SELECT id,revoked_at,(COALESCE(last_used_at, created_at) < now() - make_interval(days => %s)) AS idle "
                    "FROM import_streams WHERE user_id=%s AND id=%s AND channel='device' FOR NO KEY UPDATE", (IDLE_ROTATE_DAYS, uid, dev["id"]))
        if not r or r["revoked_at"] is not None:
            raise _err("TOKEN-REVOKED", "이 장치 토큰은 폐기됐어요.", "다시 연결하세요.")
        if r["idle"]:
            raise _err("TOKEN-EXPIRED", f"{IDLE_ROTATE_DAYS}일 동안 업로드가 없어 교체할 수 없어요.", "앱이나 대화에서 다시 연결하세요.")
        token, exp = imports.pending_in(c, uid, r["id"])
        db._audit(c, "device_rotate", uid, uid, {"device_id": r["id"], "via": "bearer", "result": "ok"})
    return {"token": token, "stream_id": dev["id"], "token_expires_at": _iso(exp)}


# ── grant (MCP) ───────────────────────────────────────

def _installs(c, uid) -> list:
    return _all(c, f"SELECT {_INST_COLS} FROM desktop_installations WHERE user_id=%s ORDER BY last_login_at DESC, id", (uid,))


def _default(rows):
    """지목 규칙 — 해제 안 된 설치본 중 최근 2분 안에 폴링한 것 가운데 가장 최근 로그인. 없으면 None.
    해제(pc_forget)한 PC 는 기본 대상이 아니다 — installation_id 로 지목할 때만 다시 연결한다(메인 판정 2026-11-02)."""
    act = [r for r in rows if r["active"] and r["revoked_at"] is None]
    return max(act, key=lambda r: (r["last_login_at"], r["id"])) if act else None


def _resolve(c, uid, installation_id):
    """받을 설치본 → (행, 켜져 있나). 지목이 없으면 기본(해제 안 된 켜진 앱 중 최근 로그인), 켜진 앱이 없으면 해제 안 된 설치본 중
    가장 최근 로그인(대기). 해제한 PC 는 지목(installation_id)할 때만. 해제 안 된 설치본이 하나도 없으면 NO-ACTIVE-APP(grant 없음 —
    앱 설치·로그인 안내, 해제한 PC 는 pc_list 로 보고 지목)."""
    if installation_id:
        r = _inst(c, uid, installation_id)
        return r, bool(r["active"])
    rows = [r for r in _installs(c, uid) if r["revoked_at"] is None]
    if not rows:
        raise _err("NO-ACTIVE-APP", "연결할 수 있는 MyCRM 앱이 없어요.",
                   "PC 에 MyCRM 앱을 설치하고 로그인하세요. 해제했던 PC 를 다시 연결하려면 pc_list 로 보고 installation_id 로 지목하세요.",
                   grant_id=None, installations=0)
    d = _default(rows)
    return (d, True) if d else (rows[0], False)


REVIVE_NOTE = "해제했던 PC를 다시 연결해요"


def _grant_out(g, inst) -> dict:
    out = {"grant_id": g["id"], "scope": g["scope"], "sent_to": inst["client_name"], "installation_id": g["installation_id"],
           "expires_at": _iso(g["expires_at"])}
    if inst["revoked_at"] is not None:
        out["note"] = REVIVE_NOTE
    return out


def _grant_create(uid, scope, installation_id) -> tuple:
    """grant 하나(같은 scope·설치본의 대기 grant 가 있으면 그것을 다시 쓴다 — 한도에 안 센다). 한도: 열린 OPEN_MAX · 하루 DAILY_MAX.
    반환 (grant 출력, 켜져 있나). 감사 token_grant."""
    with tx() as c:
        db._user_lock(c, uid)
        inst, active = _resolve(c, uid, installation_id)
        g = _one(c, "SELECT id,scope,installation_id,expires_at FROM token_grants WHERE user_id=%s AND installation_id=%s AND scope=%s "
                    "AND state='waiting' AND expires_at > now() ORDER BY created_at DESC LIMIT 1", (uid, inst["id"], scope))
        if g is None:
            n_open = _one(c, "SELECT count(*) AS n FROM token_grants WHERE user_id=%s AND state='waiting' AND expires_at > now()", (uid,))["n"]
            if n_open >= OPEN_MAX:
                raise _err("RATE-LIMIT", f"받기를 기다리는 요청이 {OPEN_MAX}개예요.", "앱을 켜서 받거나 10분 뒤 다시 하세요.")
            n_day = _one(c, f"SELECT count(*) AS n FROM token_grants WHERE user_id=%s AND created_at >= {db._KST_TODAY}", (uid,))["n"]
            if n_day >= DAILY_MAX:
                raise _err("RATE-LIMIT", f"오늘 보낼 수 있는 요청({DAILY_MAX}개)을 다 썼어요.", "내일(KST 0시 이후) 다시 하세요.")
            gid = "tg_" + secrets.token_hex(12)
            g = _one(c, "INSERT INTO token_grants (user_id,id,scope,installation_id,via,expires_at) "
                        "VALUES (%s,%s,%s,%s,%s,now() + make_interval(mins => %s)) RETURNING id,scope,installation_id,expires_at",
                     (uid, gid, scope, inst["id"], VIA, GRANT_MINUTES))
            db._audit(c, "token_grant", uid, uid, {"grant_id": gid, "scope": scope, "via": VIA, "to": inst["client_name"], "result": "created"})
        return _grant_out(g, inst), active


def _no_app(out):
    return _err("NO-ACTIVE-APP", f"켜진 MyCRM 앱이 없어요. 「{out['sent_to']}」 앱을 켜면 {GRANT_MINUTES}분 안에 받아요.",
                "사용자에게 그 PC 의 MyCRM 앱을 켜 달라고 하고, 같은 op 을 다시 부르지 말고 token_grant_status(grant_id) 로 확인하세요.", **out)


def pc_list(uid: str) -> dict:
    """내 PC(로그인한 MyCRM 앱 설치본) 목록 — 연결할 PC 고르기용. pcs[] = {installation_id, client_name, os, last_seen_at,
    active(최근 2분 안에 앱이 켜져 있었나), is_default(지목 없이 pc_connect 하면 받을 PC), revoked(대화로 해제한 PC), device_connected}.
    비어 있으면 사용자에게 PC 에 MyCRM 앱을 설치하고 로그인하라고 안내한다. IP·경로는 없다."""
    with tx() as c:
        rows = _installs(c, uid)
        d = _default(rows)
        pcs = []
        for r in rows:
            dev = _device(c, uid, r["device_id"])
            pcs.append({"installation_id": r["id"], "client_name": r["client_name"], "os": r["os"], "last_seen_at": _iso(r["last_seen_at"]),
                        "active": bool(r["active"]), "is_default": d is not None and r["id"] == d["id"], "revoked": r["revoked_at"] is not None,
                        "device_connected": bool(dev and dev["revoked_at"] is None)})
    out = {"pcs": pcs}
    if not pcs:
        out["note"] = "로그인한 MyCRM 앱이 없어요. PC 에 앱을 설치하고 로그인하면 여기에 보여요."
    return out


def pc_connect(uid: str, installation_id: str = "") -> dict:
    """이 PC(또는 지목한 PC)의 MyCRM 앱에 장치 토큰을 보낸다 — 토큰은 대화에 나오지 않고, 켜진 앱이 스스로 받아 연결한다.
    사용자가 PC 연결(해제한 PC 다시 연결 포함)을 말할 때만 부른다. 지목이 없으면 해제 안 된 PC 중 최근 2분 안에 켜져 있던 앱 가운데 가장
    최근 로그인한 PC. 해제했던 PC 는 installation_id 로 지목할 때만 — 그때 응답 note 「해제했던 PC를 다시 연결해요」.
    PC 가 둘 이상이고 사용자가 어느 PC 인지 말하지 않았으면 먼저 pc_list 로 보여 준다. 반환 {grant_id, scope:"device", sent_to(PC 이름),
    installation_id, expires_at} — 사용자에게 「PC 이름으로 보냈어요」라고 말하고 token_grant_status 로 확인한다. 켜진 앱이 없으면
    NO-ACTIVE-APP(요청은 10분 기다린다 — detail 에 grant_id·sent_to, 다시 부르지 말고 앱을 켜 달라고 안내)."""
    out, active = _grant_create(uid, "device", installation_id)
    if not active:
        raise _no_app(out)
    return out


def migration_token_send(uid: str, installation_id: str = "") -> dict:
    """이관 토큰을 PC 의 MyCRM 앱으로 보낸다(대화에 토큰이 나오지 않는다). 앱이 받으면 기존 이관 토큰은 새 토큰을 처음 쓸 때 폐기된다.
    사용자가 decide_preview 의 shown(받을 PC·폐기될 기존 토큰 수)을 보고 보내라고 말한 뒤에만 부른다. 스위치·허용 목록·표시 이름은 보낼 때와
    앱이 받을 때 다시 본다. 반환 {grant_id, scope:"migration", sent_to, installation_id, expires_at, revokes(폐기될 기존 이관 토큰 수)}.
    켜진 앱이 없으면 NO-ACTIVE-APP(요청은 10분 기다린다 — 다시 부르지 말고 앱을 켜 달라고 안내)."""
    migration.gate(uid)
    with tx() as c:
        n = migration.active_count(c, uid)
    out, active = _grant_create(uid, "migration", installation_id)
    out["revokes"] = n
    if not active:
        raise _no_app(out)
    return out


def pc_forget(uid: str, installation_id: str) -> dict:
    """PC 연결 해제 — 그 PC 의 연결 장치 토큰을 폐기하고, 기다리던 요청을 취소하고, 해제 기록을 남긴다(앱이 자동으로 다시 붙이지 않는다).
    이미 받은 활동·기록은 남는다. 사용자가 그 PC 연결을 해제하라고 말할 때만 부른다. 다시 연결은 pc_connect(사용자가 말할 때).
    반환 {installation_id, client_name, revoked:true, device_revoked(이번에 해제했나), cancelled_grants}. 멱등. 감사 pc_forget."""
    with tx() as c:
        db._user_lock(c, uid)
        inst = _inst(c, uid, installation_id, lock=True)
        c.execute("UPDATE desktop_installations SET revoked_at=COALESCE(revoked_at, now()) WHERE user_id=%s AND id=%s", (uid, inst["id"]))
        # 대화 하나로 J(JD3): 이 PC(설치본)의 서 있는 대화 허용을 지운다. 장치 쪽은 imports.revoke_in 이 지운다
        c.execute("DELETE FROM chat_provider_permits WHERE user_id=%s AND installation_id=%s", (uid, inst["id"]))
        n = c.execute("UPDATE token_grants SET state='cancelled' WHERE user_id=%s AND installation_id=%s AND state='waiting'",
                      (uid, inst["id"])).rowcount
        dev = _device(c, uid, inst["device_id"], lock=True)
        rev = bool(dev) and imports.revoke_in(c, uid, dev, via="pc_forget")
        if inst["revoked_at"] is None or rev or n:
            db._audit(c, "pc_forget", uid, uid, {"installation_id": inst["id"], "to": inst["client_name"], "cancelled": n, "result": "ok"})
    return {"installation_id": inst["id"], "client_name": inst["client_name"], "revoked": True, "device_revoked": rev, "cancelled_grants": n}


def token_grant_status(uid: str, grant_id: str) -> dict:
    """보낸 요청(grant) 상태 — {grant_id, scope, state: waiting|delivered|expired|cancelled, sent_to, expires_at, delivered_to, delivered_at}.
    delivered = PC 앱이 받아 연결했다. 토큰 값은 없다."""
    gid = grant_id if isinstance(grant_id, str) else ""
    with tx() as c:
        g = _one(c, "SELECT g.id,g.scope,g.state,g.expires_at,g.delivered_at,g.delivered_to,(g.expires_at <= now()) AS gone,i.client_name "
                    "FROM token_grants g JOIN desktop_installations i ON i.user_id=g.user_id AND i.id=g.installation_id "
                    "WHERE g.user_id=%s AND g.id=%s", (uid, gid))
    if not g:
        raise _err("NOT-FOUND", "그 요청(grant)을 찾지 못했어요.", "pc_connect·migration_token_send 가 준 grant_id 를 쓰세요.")
    state = "expired" if g["state"] == "waiting" and g["gone"] else g["state"]
    return {"grant_id": g["id"], "scope": g["scope"], "state": state, "sent_to": g["client_name"], "expires_at": _iso(g["expires_at"]),
            "delivered_to": g["delivered_to"], "delivered_at": _iso(g["delivered_at"])}


def token_list(uid: str) -> dict:
    """내 토큰 목록(값·해시 없음) — devices[] = 연결 장치 {device_id, label, active, created_at, token_expires_at, last_used_at, pc(연결된 PC 이름)}
    · migration_tokens[] = 이관 토큰 {id, label, active, created_at, expires_at, last_used_at}. 폐기는 token_revoke."""
    with tx() as c:
        devs = _all(c, "SELECT s.id,s.label,s.revoked_at,s.created_at,s.token_expires_at,s.last_used_at,"
                       "(SELECT i.client_name FROM desktop_installations i WHERE i.user_id=s.user_id AND i.device_id=s.id LIMIT 1) AS pc "
                       "FROM import_streams s WHERE s.user_id=%s AND s.channel='device' ORDER BY s.created_at DESC, s.id DESC", (uid,))
    mig = migration.token_status(uid)["tokens"]
    return {"devices": [{"device_id": d["id"], "label": d["label"], "active": d["revoked_at"] is None, "created_at": _iso(d["created_at"]),
                         "token_expires_at": _iso(d["token_expires_at"]), "last_used_at": _iso(d["last_used_at"]), "pc": d["pc"]} for d in devs],
            "migration_tokens": [{k: t.get(k) for k in ("id", "label", "active", "created_at", "expires_at", "last_used_at")} for t in mig]}


def token_revoke(uid: str, kind: str, id: str) -> dict:   # noqa: A002 — MCP 인자 이름(계획 §4)
    """토큰 폐기 — kind=device: 그 연결 장치 해제(토큰 폐기, 되살리지 않는다 — 다시 연결은 pc_connect) · kind=migration: 그 이관 토큰 폐기.
    사용자가 그 토큰을 폐기하라고 말할 때만 부른다. 반환 {kind, id, active:false}. 멱등."""
    if kind == "device":
        out = imports.device_revoke(uid, id)
        return {"kind": kind, "id": out["device"]["id"], "active": out["device"]["active"]}
    if kind == "migration":
        out = migration.token_revoke(uid, id)
        return {"kind": kind, "id": out["info"]["id"], "active": out["info"]["active"]}
    raise _err("ARG-INVALID", "kind 는 device 또는 migration 이에요.", "token_list 로 확인하세요.")


# ── redeem (앱 세션) ───────────────────────────────────

def grant_redeem(uid: str, grant_id, installation_id) -> dict:
    """POST /desktop/grants/{id}/redeem — 앱 세션 + 헤더(web 이 검사). 계정 일치(NOT-OWNER) · 설치본 일치(INSTALLATION-UNKNOWN) ·
    미사용(GRANT-USED) · 미만료(GRANT-EXPIRED) · scope 검사 뒤 **그 자리에서** 토큰 발급. 일회용(조건부 UPDATE).
    device = 설치본의 살아 있는 장치면 대기 토큰(M2), 없거나 해제면 새 장치 + 해제 기록 풀림(대화 요청 = 사용자 의사).
    migration = 스위치·allowlist·표시 이름 재검사 → 새 이관 토큰(M2). 반환 {grant_id, scope, token, device_id, device_label, account_label,
    token_expires_at} — 토큰은 이 응답에만. 감사 token_grant_redeem(값 없음)."""
    gid = grant_id if isinstance(grant_id, str) else ""
    if not _GRANT_RE.match(gid):
        raise _err("NOT-FOUND", "그 요청(grant)을 찾지 못했어요.")
    with tx() as c:
        db._user_lock(c, uid)
        g = _one(c, "SELECT user_id,id,scope,installation_id,state,(expires_at <= now()) AS gone FROM token_grants WHERE id=%s FOR UPDATE", (gid,))
        if not g:
            raise _err("NOT-FOUND", "그 요청(grant)을 찾지 못했어요.")
        if g["user_id"] != uid:
            raise _err("NOT-OWNER", "다른 계정으로 보낸 요청이에요.", "앱에서 지금 계정으로 다시 등록하세요(옛 계정 장치 토큰은 지운다).")
        inst = _inst(c, uid, installation_id, lock=True)
        if g["installation_id"] != inst["id"]:
            raise _err("INSTALLATION-UNKNOWN", "이 PC 로 보낸 요청이 아니에요.")
        if g["state"] == "delivered":
            raise _err("GRANT-USED", "이미 받은 요청이에요.")
        if g["state"] != "waiting" or g["gone"]:
            raise _err("GRANT-EXPIRED", "요청이 만료됐거나 취소됐어요.", "대화에서 다시 요청하세요.")
        if g["scope"] == "device":
            out = _device_token(c, uid, inst, allow_new=True, revive=True, via="grant")
            token, dev_id, dev_label, exp, to = out["token"], out["device"]["id"], out["device"]["label"], out["token_expires_at"], out["device"]["label"]
        else:
            migration.gate(uid)
            db.name_gate(uid)
            m = migration.token_issue_in(c, uid, via="grant")
            token, dev_id, dev_label, exp, to = m["token"], None, None, m["info"]["expires_at"], inst["client_name"]
        c.execute("UPDATE token_grants SET state='delivered', delivered_at=now(), delivered_to=%s WHERE user_id=%s AND id=%s AND state='waiting'",
                  (to, uid, gid))
        db._audit(c, "token_grant_redeem", uid, uid, {"grant_id": gid, "scope": g["scope"], "via": VIA, "to": to, "result": "ok"})
        return {"grant_id": gid, "scope": g["scope"], "token": token, "device_id": dev_id, "device_label": dev_label,
                "account_label": _account(c, uid), "token_expires_at": exp}


# ── CLI --browser (RFC 8252 loopback, 앱 없는 대체 경로) ──────────

def cli_issue(uid: str, scope: str, client_name=None) -> dict:
    """POST /desktop/cli/claim — loopback 넘김 코드 교환(web 이 PKCE·state·일회용을 본 뒤) → scope 별 토큰. 토큰은 이 응답에만.
    device = 새 연결 장치(이름 = client_name, 표시 이름 관문·전역 크기 = write_gate("device_connect")) → {scope, token, stream_id,
    token_expires_at, account_label} · migration = 스위치·allowlist·표시 이름 재검사 → 새 이관 토큰(M2) → {scope, token, token_id,
    expires_at, account_label}."""
    if scope == "device":
        db.write_gate("device_connect", {"label": client_name or ""}, uid)
        out = imports.device_connect(uid, client_name)
        with tx() as c:
            acct = _account(c, uid)
        return {"scope": scope, "token": out["token"], "stream_id": out["device"]["id"], "token_expires_at": out["device"]["token_expires_at"],
                "account_label": acct}
    if scope == "migration":
        migration.gate(uid)
        db.write_gate("migration_token_issue", {}, uid)
        out = migration.token_issue(uid)
        with tx() as c:
            acct = _account(c, uid)
        return {"scope": scope, "token": out["token"], "token_id": out["info"]["id"], "expires_at": out["info"]["expires_at"],
                "account_label": acct}
    raise _err("ARG-INVALID", "scope 는 device 또는 migration 이에요.")


# ── 정리 회차 ─────────────────────────────────────────

def expire_round() -> int:
    """imports.expire_pending 회차 — 만료 지난 대기 grant → expired · KEEP_DAYS 지난 끝난 grant 삭제 · 만료 지난 대기 토큰(M2) 비움. 반환 건수."""
    with tx() as c:
        n = c.execute("UPDATE token_grants SET state='expired' WHERE state='waiting' AND expires_at <= now()").rowcount
        n += c.execute("DELETE FROM token_grants WHERE state <> 'waiting' AND created_at < now() - make_interval(days => %s)", (KEEP_DAYS,)).rowcount
        n += c.execute("UPDATE import_streams SET pending_token_id=NULL, pending_secret_hash=NULL, pending_expires_at=NULL "
                       "WHERE pending_expires_at IS NOT NULL AND pending_expires_at <= now()").rowcount
    return n


# ── decide_preview shown 빌더 (facade K2 — main.py 가 facade.PREVIEWS 에 더한다) ──
# 반환 (스냅샷, shown, impact, irreversible). 읽기만 한다. 시각으로 바뀌는 값(last_seen_at)은 스냅샷에 넣지 않는다 — 받을 PC id 를 넣는다.

def _pv_migration_token_send(uid, p):
    migration.gate(uid)
    with tx() as c:
        inst, active = _resolve(c, uid, p.get("installation_id") or "")
        toks = _all(c, "SELECT id FROM migration_tokens WHERE user_id=%s AND revoked_at IS NULL AND expires_at > now() ORDER BY id", (uid,))
    n = len(toks)
    shown = {"할 일": "이관 토큰을 PC 앱으로 보내기(대화에 토큰은 나오지 않아요)", "받을 PC": inst["client_name"],
             "기존 이관 토큰": f"기존 이관 토큰 {n}개가 폐기돼요(새 토큰을 처음 쓸 때)" if n else "폐기될 기존 이관 토큰 없음",
             "유효 기간": f"{migration.TOKEN_DAYS}일"}
    if not active:
        shown["앱 상태"] = "지금 켜져 있지 않아요 — 앱을 켜면 10분 안에 받아요"
    snap = {"installation_id": inst["id"], "tokens": [t["id"] for t in toks]}
    return snap, shown, {"installation_id": inst["id"], "sent_to": inst["client_name"], "revokes": n}, False


def _pv_pc_forget(uid, p):
    with tx() as c:
        inst = _inst(c, uid, p.get("installation_id"))
        dev = _device(c, uid, inst["device_id"])
        n = _one(c, "SELECT count(*) AS n FROM token_grants WHERE user_id=%s AND installation_id=%s AND state='waiting' AND expires_at > now()",
                 (uid, inst["id"]))["n"]
    shown = {"PC": inst["client_name"], "OS": inst["os"],
             "연결 장치": (dev["label"] + ("" if dev["revoked_at"] is None else "(이미 해제)")) if dev else "없음",
             "결과": "이 PC 연결 해제 — 장치 토큰 폐기, 앱이 자동으로 다시 붙지 않아요(다시 연결은 대화에서). 이미 받은 활동·기록은 남아요."}
    if n:
        shown["취소될 요청"] = f"{n}개"
    snap = {"revoked": inst["revoked_at"] is not None, "device_id": inst["device_id"], "device_revoked": bool(dev and dev["revoked_at"] is not None),
            "waiting": n}
    return snap, shown, {"installation_id": inst["id"], "device_id": inst["device_id"]}, False


def _pv_token_revoke(uid, p):
    kind, tid = p.get("kind"), str(p.get("id") or "")
    with tx() as c:
        if kind == "device":
            r = _one(c, "SELECT id,label,revoked_at FROM import_streams WHERE user_id=%s AND id=%s AND channel='device'", (uid, tid))
            if not r:
                raise imports._nf("그 장치")
            shown = {"종류": "장치 토큰(연결 장치)", "이름": r["label"], "지금": "해제됨" if r["revoked_at"] else "연결됨",
                     "결과": "연결 해제 — 이 장치 토큰은 다시 쓸 수 없어요(되살리지 않음, 다시 연결은 새로)"}
        elif kind == "migration":
            r = _one(c, "SELECT id,label,revoked_at FROM migration_tokens WHERE user_id=%s AND id=%s", (uid, tid))
            if not r:
                raise imports._nf("그 이관 토큰")
            shown = {"종류": "이관 토큰", "이름": r["label"], "지금": "폐기됨" if r["revoked_at"] else "살아 있음",
                     "결과": "폐기 — 이 이관 토큰은 다시 쓸 수 없어요"}
        else:
            raise _err("ARG-INVALID", "kind 는 device 또는 migration 이에요.", "token_list 로 확인하세요.")
    return {"revoked": r["revoked_at"] is not None}, shown, {"kind": kind, "id": r["id"]}, True


PREVIEWS = {
    "migration_token_send": _pv_migration_token_send,
    "pc_forget": _pv_pc_forget,
    "token_revoke": _pv_token_revoke,
}
