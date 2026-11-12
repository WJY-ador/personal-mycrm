"""관리자 프로필 · 조직 기능 설정 · 변경 기록 (2026-11-12, Salesforce Profile·Feature Settings·Setup Audit Trail 꼴).

판정은 feature_on(uid, feature) 하나다. 기능이 그 사용자에게 열리는 조건:
  ① 환경변수 비상 끄기가 아님 — CRM_<env> 가 "1" 이나 빈 값이면 통과, 그 밖의 값("0" 등)이면 조직 설정과 상관없이 꺼짐
  ② 조직 설정 켜짐 — org_features 행. 행이 아직 없으면(시작 시드 전) 옛 의미 그대로 env == "1"
  ③ 프로필 권한 있음 — scope="profile" 기능만. 사용자 문맥이 없는 경로(uid None: 정리 작업·CLI)는 ①②만 본다
프로필: 사용자마다 하나(users.profile_id, NULL = 표준 사용자). 시스템 관리자 = 관리자 화면 + 모든 기능 권한(고정).
users.role 은 거울이다 — 진실은 profile_id. 바꾸는 곳은 _assign 한 곳이고 같은 트랜잭션에서 role 을 맞춘다.
캐시(P9): 조직 설정·프로필 권한·사용자→프로필을 CACHE_SECONDS 동안 프로세스 메모리에 둔다. 관리자 저장은 즉시 비운다. env 는 매번 읽는다.
MCP 로는 바꾸지 않는다(관리자 기능). 사용자는 me_get 의 access 로 자기 프로필 이름·켜진 기능을 본다.
"""

import secrets
import time
from dataclasses import dataclass

from psycopg.types.json import Jsonb

import db
from envnames import env

SYSTEM_ADMIN, STANDARD_USER = "system_admin", "standard_user"
BUILTIN = {SYSTEM_ADMIN: ("시스템 관리자", "관리자 화면과 모든 기능 권한. 권한 체크는 바꿀 수 없어요."),
           STANDARD_USER: ("표준 사용자", "모든 사용자 기능 권한. 관리자 화면은 없어요.")}
CACHE_SECONDS = 5
NAME_MAX, DESC_MAX = 80, 500
CHANGES_LIST = 200


@dataclass(frozen=True)
class Feature:
    key: str
    env: str          # CRM_ 뒤 이름(비상 끄기·첫 시드)
    label: str
    note: str
    scope: str        # "profile" = 조직 설정 + 프로필 권한 · "org" = 조직 설정만


# 정본 — 순서 = 화면 순서. 게이트 상수(ATOMIC_DISPATCH_READY·PROVIDER_LAUNCH_READY)·개발 스위치·비밀값은 넣지 않는다.
FEATURES = (
    Feature("webchat", "WEBCHAT_ENABLED", "웹 AI 대화", "구독 AI 채팅 화면·장치 연결", "profile"),
    Feature("chat_mcp", "CHAT_MCP_ENABLED", "대화 도구 호출", "웹 대화에서 내 기록 도구를 부르기(웹 AI 대화도 켜져야 해요)", "profile"),
    Feature("trash", "TRASH_ENABLED", "휴지통", "삭제를 휴지통으로 옮기고 7일 안에 복원", "profile"),
    Feature("inbox_approvals", "INBOX_APPROVALS_ENABLED", "저장 승인 대기 승인", "장치에서 온 글을 승인해 기록으로 남기기", "profile"),
    Feature("converse", "CONVERSE_ENABLED", "PC 대화 작업", "대화와 원문 던지기를 내 PC 에이전트로 보내기", "profile"),
    Feature("routine", "ROUTINE_ENABLED", "PC 루틴 작업", "예약 루틴 결과 받기", "profile"),
    Feature("migration_mcp", "MIGRATION_MCP_ENABLED", "대화 이관", "대화(MCP)로 옛 자료 이관(허용 목록도 봐요)", "profile"),
    Feature("imports", "IMPORTS_ENABLED", "장치 수집 수신", "연결 장치에서 오는 수집 전체", "org"),
    Feature("activity_imports", "ACTIVITY_IMPORTS_ENABLED", "활동 즉시 저장", "장치 활동을 바로 저장", "org"),
    Feature("unattended_summary_imports", "UNATTENDED_SUMMARY_IMPORTS_ENABLED", "무인 AI 요약 접수", "약관 확인 전엔 꺼 둬요", "org"),
    Feature("board_migration", "BOARD_MIGRATION_ENABLED", "board 이전", "이전 CLI·웹 반영(허용 목록도 봐요)", "org"),
    Feature("download_public", "DOWNLOAD_PUBLIC", "설치 파일 공개 링크", "/download 직링크 보이기", "org"),
)
BY_KEY = {f.key: f for f in FEATURES}
BY_ENV = {f.env: f for f in FEATURES}
PROFILE_FEATURES = tuple(f.key for f in FEATURES if f.scope == "profile")

_cache = {"org": (0.0, None), "perms": {}, "user": {}}


def clear_cache():
    """관리자 저장 뒤·시험에서 부른다."""
    _cache["org"] = (0.0, None)
    _cache["perms"].clear()
    _cache["user"].clear()


def env_state(f: Feature) -> str:
    """"off" = 비상 끄기 · "on" = 1 · "" = 비어 있음(조직 설정을 따름)."""
    v = env(f.env, "")
    return "" if v == "" else "on" if v == "1" else "off"


def _fresh(at):
    return time.monotonic() - at < CACHE_SECONDS


def _load(c, fn, stale=None):
    """DB 에서 읽는다. 실패하면 직전 캐시 값(stale)이 있을 때만 그것을 쓴다(일시 장애에 판정이 흔들리지 않게). 없으면 예외 그대로."""
    try:
        if c is not None:
            return fn(c)
        with db.tx() as cc:
            return fn(cc)
    except Exception:
        if stale is None or c is not None:
            raise
        return stale


def _org(c=None) -> dict:
    at, val = _cache["org"]
    if val is None or not _fresh(at):
        val = _load(c, lambda cc: {r["feature"]: r["enabled"] for r in db._all(cc, "SELECT feature, enabled FROM org_features")}, val)
        _cache["org"] = (time.monotonic(), val)
    return val


def _profile_of(uid, c=None) -> str:
    hit = _cache["user"].get(uid)
    if hit and _fresh(hit[0]):
        return hit[1]
    r = _load(c, lambda cc: db._one(cc, "SELECT profile_id FROM users WHERE id=%s", (str(uid),)), {"profile_id": hit[1]} if hit else None)
    pid = (r or {}).get("profile_id") or STANDARD_USER
    _cache["user"][uid] = (time.monotonic(), pid)
    return pid


def _perms(pid, c=None) -> frozenset:
    if pid == SYSTEM_ADMIN:
        return frozenset(PROFILE_FEATURES)
    hit = _cache["perms"].get(pid)
    if hit and _fresh(hit[0]):
        return hit[1]
    val = frozenset(r["feature"] for r in _load(c, lambda cc: db._all(cc, "SELECT feature FROM access_profile_perms WHERE profile_id=%s", (pid,)),
                                                [{"feature": k} for k in hit[1]] if hit else None))
    _cache["perms"][pid] = (time.monotonic(), val)
    return val


def org_on(feature: str, c=None) -> bool:
    """①② — 환경변수 비상 끄기 + 조직 설정(행 없으면 env == "1")."""
    f = BY_KEY.get(feature)
    if f is None:
        raise ValueError(feature)   # 오타로 늘 꺼지는 것을 막는다
    st = env_state(f)
    if st == "off":
        return False
    org = _org(c)
    return org[feature] if feature in org else st == "on"


def feature_on(uid, feature: str, c=None) -> bool:
    """판정 정본. uid None = 사용자 문맥 없음(조직 설정만). c = 열린 트랜잭션 안에서 부를 때 그 연결(풀 중첩 방지)."""
    if not org_on(feature, c):
        return False
    if BY_KEY[feature].scope == "org" or not uid:
        return True
    return feature in _perms(_profile_of(uid, c), c)


def access_of(uid) -> dict:
    """me_get 용 — {profile: 이름, features: [켜진 기능 키]}. 읽기만."""
    pid = _profile_of(uid)
    with db.tx() as c:
        r = db._one(c, "SELECT name FROM access_profiles WHERE id=%s", (pid,))
    return {"profile": (r or {}).get("name") or BUILTIN[STANDARD_USER][0],
            "features": [f.key for f in FEATURES if feature_on(uid, f.key)]}


# ── 스키마 이관(init_schema 안) · 첫 시드(서버 시작) ─────────────

def migrate(c):
    """init_schema 끝에서 매번. 표는 schema.sql 이 만든다. ① 기본 프로필 2개 ② 기능 키가 처음 보일 때 표준 사용자에게 권한(한 번만 —
    schema_marks 표식, 관리자가 뺀 권한을 되살리지 않는다) ③ users.profile_id 열(FK) ④ role=admin 인데 프로필이 비면 시스템 관리자
    ⑤ role 거울을 프로필에 맞춘다."""
    for pid, (name, desc) in BUILTIN.items():
        c.execute("INSERT INTO access_profiles (id,name,description,builtin) VALUES (%s,%s,%s,true) ON CONFLICT (id) DO NOTHING",
                  (pid, name, desc))
    for key in PROFILE_FEATURES:
        if db._one(c, "INSERT INTO schema_marks (key) VALUES (%s) ON CONFLICT (key) DO NOTHING RETURNING key", (f"perm_seed:{key}",)):
            c.execute("INSERT INTO access_profile_perms (profile_id,feature) VALUES (%s,%s) ON CONFLICT DO NOTHING", (STANDARD_USER, key))
    if not db._has_col(c, "users", "profile_id"):
        c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS profile_id text")
    if not db._has_constraint(c, "users", "fk_users_profile"):
        c.execute("ALTER TABLE users ADD CONSTRAINT fk_users_profile FOREIGN KEY (profile_id) REFERENCES access_profiles(id)")
    c.execute("UPDATE users SET profile_id=%s WHERE role='admin' AND profile_id IS NULL", (SYSTEM_ADMIN,))
    c.execute("UPDATE users SET role = CASE WHEN profile_id=%s THEN 'admin' ELSE 'user' END "
              "WHERE role <> CASE WHEN profile_id=%s THEN 'admin' ELSE 'user' END", (SYSTEM_ADMIN, SYSTEM_ADMIN))


def seed_org_from_env():
    """서버 시작 때(main.lifespan) — 조직 설정 행이 없는 기능만 지금 env 값(== "1")으로 넣는다. 두 번째 시작부터는 덮어쓰지 않는다.
    넣은 것은 변경 기록(kind=seed)에 남긴다. 반환 = 넣은 기능 키 목록."""
    out = []
    with db.tx() as c:
        for f in FEATURES:
            on = env(f.env, "") == "1"
            if db._one(c, "INSERT INTO org_features (feature,enabled) VALUES (%s,%s) ON CONFLICT (feature) DO NOTHING RETURNING feature",
                       (f.key, on)):
                _log(c, None, "seed", f.key, None, {"enabled": on})
                out.append(f.key)
    clear_cache()
    return out


# ── 관리자 변경 — 전부 한 트랜잭션 · db.ADMIN_LOCK · 실행자 재확인 · 변경 기록 ─────────────

def _log(c, actor, kind, subject, before, after):
    c.execute("INSERT INTO setup_changes (actor_id,kind,subject,from_val,to_val) VALUES (%s,%s,%s,%s,%s)",
              (actor, kind, subject, Jsonb(before) if before is not None else None, Jsonb(after) if after is not None else None))


def _actor(c, actor_id):
    c.execute("SELECT pg_advisory_xact_lock(%s)", (db.ADMIN_LOCK,))
    a = db._one(c, "SELECT profile_id,blocked_at,status FROM users WHERE id=%s", (str(actor_id or ""),))
    if not a or a["profile_id"] != SYSTEM_ADMIN or a["blocked_at"] is not None or a["status"] != "active":
        raise db.CrmError("FORBIDDEN", "관리자만 바꿀 수 있어요.")


def _profile(c, pid, lock=False):
    p = db._one(c, "SELECT id,name,description,builtin FROM access_profiles WHERE id=%s" + (" FOR UPDATE" if lock else ""), (str(pid or ""),))
    if not p:
        raise db.CrmError("NOT-FOUND", "그 프로필을 찾지 못했어요.", "새로 고침한 뒤 다시 해 보세요.")
    return p


def _clean(name, desc):
    name, desc = (name or "").strip(), (desc or "").strip()
    if not 1 <= len(name) <= NAME_MAX:
        raise db.CrmError("ARG-INVALID", f"이름은 1~{NAME_MAX}자예요.")
    if len(desc) > DESC_MAX:
        raise db.CrmError("ARG-INVALID", f"설명은 {DESC_MAX}자까지예요.")
    return name, desc


def _name_free(c, name, pid=None):
    if db._one(c, "SELECT 1 AS x FROM access_profiles WHERE name=%s AND id <> %s", (name, pid or "")):
        raise db.CrmError("PROFILE-NAME-TAKEN", "같은 이름의 프로필이 있어요.", "다른 이름을 쓰세요.")


def _perm_set(c, pid):
    if pid == SYSTEM_ADMIN:
        return list(PROFILE_FEATURES)
    have = {r["feature"] for r in db._all(c, "SELECT feature FROM access_profile_perms WHERE profile_id=%s", (pid,))}
    return [k for k in PROFILE_FEATURES if k in have]


def _assign(c, actor, tid, pid):
    """사용자 프로필 지정 — role 거울을 같이 맞춘다. 시스템 관리자 0명이 되면 LAST-ADMIN. 관리자를 잃으면 웹 세션도 끊는다(옛 회수와 같다).
    대상 행은 FOR UPDATE 로 잠근다. 반환 {changed, from, to}."""
    t = db._one(c, "SELECT id,profile_id FROM users WHERE id=%s FOR UPDATE", (str(tid or ""),))
    if not t:
        raise db.CrmError("NOT-FOUND", "그 계정을 찾지 못했어요.", "새로 고침한 뒤 다시 해 보세요.")
    _profile(c, pid)
    old = t["profile_id"] or STANDARD_USER
    if old == pid:
        return {"changed": False, "from": old, "to": pid}
    if old == SYSTEM_ADMIN and db._one(c, "SELECT count(*) AS n FROM users WHERE profile_id=%s", (SYSTEM_ADMIN,))["n"] <= 1:
        raise db.CrmError("LAST-ADMIN", "마지막 시스템 관리자는 다른 프로필로 바꿀 수 없어요.", "다른 사람을 먼저 시스템 관리자로 지정하세요.")
    lose = old == SYSTEM_ADMIN
    c.execute("UPDATE users SET profile_id=%s, role=%s" + (", web_revoked_before=now()" if lose else "") + " WHERE id=%s",
              (pid, "admin" if pid == SYSTEM_ADMIN else "user", t["id"]))
    _log(c, actor, "user_profile", t["id"], {"profile": old}, {"profile": pid})
    return {"changed": True, "from": old, "to": pid}


def assign_in(c, actor, tid, pid):
    """db.admin_bootstrap·admin_recover·admin_act 가 자기 트랜잭션(이미 ADMIN_LOCK) 안에서 부른다. 실행자 검사는 부르는 쪽이 한다."""
    out = _assign(c, actor, tid, pid)
    clear_cache()
    return out


def user_profile_set(actor, tid, pid):
    with db.tx() as c:
        _actor(c, actor)
        out = _assign(c, actor, tid, pid)
    clear_cache()
    return out


def profile_clone(actor, src, name, desc=""):
    """새 프로필 = 원본 복제(권한 체크 복사). 시스템 관리자를 복제해도 관리자 화면은 따라오지 않는다(관리자 = 시스템 관리자 프로필뿐)."""
    name, desc = _clean(name, desc)
    with db.tx() as c:
        _actor(c, actor)
        _profile(c, src)
        _name_free(c, name)
        pid = "p_" + secrets.token_hex(6)
        perms = _perm_set(c, src)
        c.execute("INSERT INTO access_profiles (id,name,description,builtin) VALUES (%s,%s,%s,false)", (pid, name, desc))
        for k in perms:
            c.execute("INSERT INTO access_profile_perms (profile_id,feature) VALUES (%s,%s)", (pid, k))
        _log(c, actor, "profile_create", pid, None, {"name": name, "from": src, "perms": perms})
    clear_cache()
    return {"id": pid}


def profile_update(actor, pid, name, desc, perms):
    """이름·설명·기능 권한 체크 저장. perms = 체크된 기능 키 모음(모르는 키는 ARG-INVALID). 시스템 관리자 권한은 고정(바꾸려 하면 거절)."""
    name, desc = _clean(name, desc)
    perms = set(perms or ())
    if perms - set(PROFILE_FEATURES):
        raise db.CrmError("ARG-INVALID", "모르는 기능 권한이에요.")
    with db.tx() as c:
        _actor(c, actor)
        p = _profile(c, pid, lock=True)
        _name_free(c, name, p["id"])
        before = _perm_set(c, p["id"])
        if p["id"] == SYSTEM_ADMIN and perms != set(PROFILE_FEATURES):
            raise db.CrmError("PROFILE-FIXED", "시스템 관리자의 기능 권한은 바꿀 수 없어요.", "복제한 프로필에서 바꾸세요.")
        changed = False
        if (name, desc) != (p["name"], p["description"]):
            c.execute("UPDATE access_profiles SET name=%s, description=%s, updated=now() WHERE id=%s", (name, desc, p["id"]))
            _log(c, actor, "profile_update", p["id"], {"name": p["name"], "description": p["description"]},
                 {"name": name, "description": desc})
            changed = True
        after = [k for k in PROFILE_FEATURES if k in perms]
        if p["id"] != SYSTEM_ADMIN and after != before:
            c.execute("DELETE FROM access_profile_perms WHERE profile_id=%s", (p["id"],))
            for k in after:
                c.execute("INSERT INTO access_profile_perms (profile_id,feature) VALUES (%s,%s)", (p["id"], k))
            c.execute("UPDATE access_profiles SET updated=now() WHERE id=%s", (p["id"],))
            _log(c, actor, "profile_perm", p["id"], {"perms": before}, {"perms": after})
            changed = True
    clear_cache()
    return {"changed": changed}


def profile_delete(actor, pid):
    with db.tx() as c:
        _actor(c, actor)
        p = _profile(c, pid, lock=True)
        if p["builtin"]:
            raise db.CrmError("PROFILE-BUILTIN", "기본 프로필은 지울 수 없어요.")
        n = db._one(c, "SELECT count(*) AS n FROM users WHERE profile_id=%s", (p["id"],))["n"]
        if n:
            raise db.CrmError("PROFILE-IN-USE", f"이 프로필을 쓰는 사용자가 {n}명 있어요.", "사용자 프로필을 먼저 바꾸세요.")
        perms = _perm_set(c, p["id"])
        c.execute("DELETE FROM access_profiles WHERE id=%s", (p["id"],))
        _log(c, actor, "profile_delete", p["id"], {"name": p["name"], "perms": perms}, None)
    clear_cache()
    return {"deleted": True}


def org_set(actor, feature, enabled: bool):
    if feature not in BY_KEY or not isinstance(enabled, bool):
        raise db.CrmError("ARG-INVALID", "모르는 기능이에요.")
    with db.tx() as c:
        _actor(c, actor)
        r = db._one(c, "SELECT enabled FROM org_features WHERE feature=%s FOR UPDATE", (feature,))
        before = r["enabled"] if r else env(BY_KEY[feature].env, "") == "1"
        if r and before == enabled:
            return {"changed": False}
        c.execute("INSERT INTO org_features (feature,enabled,updated,updated_by) VALUES (%s,%s,now(),%s) "
                  "ON CONFLICT (feature) DO UPDATE SET enabled=EXCLUDED.enabled, updated=now(), updated_by=EXCLUDED.updated_by",
                  (feature, enabled, actor))
        _log(c, actor, "org_feature", feature, {"enabled": before}, {"enabled": enabled})
    clear_cache()
    return {"changed": True}


# ── 관리자 화면 읽기 ─────────────

def profiles():
    with db.tx() as c:
        rows = db._all(c, "SELECT p.id,p.name,p.description,p.builtin,p.updated,"
                          "(SELECT count(*) FROM users u WHERE COALESCE(u.profile_id,%s)=p.id) AS users "
                          "FROM access_profiles p ORDER BY p.builtin DESC, p.name, p.id", (STANDARD_USER,))
        return [{**r, "perms": _perm_set(c, r["id"])} for r in rows]


def profile_detail(pid):
    with db.tx() as c:
        p = _profile(c, pid)
        users = db._all(c, "SELECT id,email,blocked_at,status FROM users WHERE COALESCE(profile_id,%s)=%s ORDER BY created, id",
                        (STANDARD_USER, p["id"]))
        return {**p, "perms": _perm_set(c, p["id"]), "users": users}


def user_profiles() -> dict:
    """{user id: profile id} — 사용자 목록 화면."""
    with db.tx() as c:
        return {r["id"]: r["profile_id"] or STANDARD_USER for r in db._all(c, "SELECT id,profile_id FROM users")}


def org_rows():
    org = _org()
    out = []
    for f in FEATURES:
        st = env_state(f)
        val = org[f.key] if f.key in org else st == "on"
        out.append({"feature": f, "org": val, "seeded": f.key in org, "env": st, "effective": org_on(f.key)})
    return out


def changes(limit=CHANGES_LIST):
    with db.tx() as c:
        return db._all(c, "SELECT s.at,s.actor_id,a.email AS actor_email,s.kind,s.subject,s.from_val,s.to_val,t.email AS target_email,"
                          "p.name AS profile_name FROM setup_changes s LEFT JOIN users a ON a.id=s.actor_id "
                          "LEFT JOIN users t ON s.kind='user_profile' AND t.id=s.subject "
                          "LEFT JOIN access_profiles p ON s.kind LIKE 'profile%%' AND p.id=s.subject "
                          "ORDER BY s.at DESC, s.id DESC LIMIT %s", (limit,))
