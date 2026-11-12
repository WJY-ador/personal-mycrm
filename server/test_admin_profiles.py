"""관리자 프로필 · 조직 기능 설정 · 변경 기록 시험 (2026-11-12, 명세 notes/plans/2026-11-12_관리자-프로필-구현명세.md 4절).

실행: DATABASE_URL=postgresql://localhost/crm_test_admin_profiles python3 server/test_admin_profiles.py
가드: server/.env 를 읽지 않는다(운영 DB 폴백 사고 방지) — DATABASE_URL 을 명시해야 하고, 호스트는 로컬, DB 이름은 crm_test 로 시작해야 한다.
시험 DB 의 조직 설정·시스템 관리자 지정을 처음에 비운다(전용 DB 라서). 자료는 전부 합성.

A. 스키마 — init_schema 2회 멱등 · 기본 프로필 2개 · 표준 사용자 권한 시드는 한 번만(뺀 권한을 되살리지 않는다) · role=admin → 시스템 관리자
B. 판정 — 조직 꺼짐 = 꺼짐 · 조직 켜짐 + 프로필 권한 없음 = 꺼짐 · 둘 다 = 켜짐 · env 0 = 꺼짐 · 행 없음 = env == "1" · uid 없음 = 조직만
C. 초기값 — 첫 시드 = 지금 env 값 · 두 번째 시드는 덮어쓰지 않는다 · 변경 기록 seed
D. 관리자만 — 실행자 비관리자 FORBIDDEN · admin_db 조회자 FORBIDDEN · HTTP 비관리자 404 · Origin 403 · form 400
E. 보호 — 마지막 시스템 관리자 LAST-ADMIN · 기본 프로필 삭제 거절 · 사용자 붙은 프로필 삭제 거절 · 시스템 관리자 권한 고정
F. 변경 기록 — 조직 설정·프로필 만들기·이름·권한·삭제·사용자 지정(전·후 값)
G. 기존 경로 — admin_act 부여·회수 · admin_recover = 프로필 지정(role 거울) · trash_on·job_switch_on·webchat.enabled 가 프로필을 본다 · me_get access
H. 화면 — 관리자 GET 200·스크립트 0·CSP · 복제·저장·조직 켜기·사용자 프로필 바꾸기 POST 303 · 정적: 화면 모듈은 admin_db 만 부른다
"""
import asyncio
import os
import re
import secrets
import sys
import urllib.parse
from pathlib import Path

HERE = Path(__file__).parent
URL = os.environ.get("DATABASE_URL", "")
if not URL:
    raise SystemExit("중단: DATABASE_URL 을 명시하세요(예: postgresql://localhost/crm_test_admin_profiles). server/.env 는 읽지 않아요.")
_u = urllib.parse.urlsplit(URL)
if _u.hostname not in ("localhost", "127.0.0.1", "::1", None) or not _u.path.lstrip("/").startswith("crm_test"):
    raise SystemExit("중단: 로컬 시험 DB(이름 crm_test*)만 허용해요.")
PUBLIC = "http://127.0.0.1:8800"
os.environ.pop("CRM_DEV", None)
os.environ.pop("CRM_DEV_USER", None)   # CI 잡 env 에 있다 — DEV 없이 DEV_USER 만 있으면 기동 거절
os.environ["AUTHKIT_ISSUER"] = "https://fake.authkit.test"
os.environ["CRM_PUBLIC_URL"] = PUBLIC
sys.path.insert(0, str(HERE))

import httpx  # noqa: E402

import admin_db  # noqa: E402
import db  # noqa: E402
import features  # noqa: E402
import main  # noqa: E402
import webchat  # noqa: E402

ENVS = ["CRM_" + f.env for f in features.FEATURES]
TAG = secrets.token_hex(3)


def expect(code, fn, *a, **k):
    try:
        fn(*a, **k)
    except db.CrmError as e:
        assert e.code == code, (e.code, code, e.message)
        return e
    raise AssertionError(f"{code} 이 나야 하는데 성공했어요")


def sql(q, args=()):
    with db.tx() as c:
        r = c.execute(q, args)
        return r.fetchall() if r.description else None


def user(name):
    return db.user_by_email(f"{name}-{TAG}@example.com")["id"]


def org(key, on):
    sql("INSERT INTO org_features (feature,enabled) VALUES (%s,%s) ON CONFLICT (feature) DO UPDATE SET enabled=EXCLUDED.enabled", (key, on))
    features.clear_cache()


def setenv(**kv):
    for k, v in kv.items():
        if v is None:
            os.environ.pop("CRM_" + k, None)
        else:
            os.environ["CRM_" + k] = v


def changes_for(subject):
    return sql("SELECT kind,actor_id,from_val,to_val FROM setup_changes WHERE subject=%s ORDER BY id", (subject,))


def test_schema(admin):
    db.init_schema()
    db.init_schema()
    p = {r["id"]: r for r in sql("SELECT id,name,builtin FROM access_profiles WHERE builtin")}
    assert set(p) == {features.SYSTEM_ADMIN, features.STANDARD_USER} and p["system_admin"]["name"] == "시스템 관리자"
    assert {r["feature"] for r in sql("SELECT feature FROM access_profile_perms WHERE profile_id='standard_user'")} == set(features.PROFILE_FEATURES)
    sql("DELETE FROM access_profile_perms WHERE profile_id='standard_user' AND feature='routine'")
    db.init_schema()
    assert not sql("SELECT 1 FROM access_profile_perms WHERE profile_id='standard_user' AND feature='routine'"), "뺀 권한을 되살리지 않는다(시드 한 번)"
    sql("INSERT INTO access_profile_perms (profile_id,feature) VALUES ('standard_user','routine')")
    # role=admin 인데 프로필이 비면 시스템 관리자로(배포 직후 이관) · role 거울
    legacy = user("legacy")
    sql("UPDATE users SET role='admin', profile_id=NULL WHERE id=%s", (legacy,))
    db.init_schema()
    assert sql("SELECT role,profile_id FROM users WHERE id=%s", (legacy,))[0] == {"role": "admin", "profile_id": "system_admin"}
    sql("UPDATE users SET role='user', profile_id=NULL WHERE id=%s", (legacy,))
    assert "user_id" not in {r["column_name"] for r in sql("SELECT column_name FROM information_schema.columns WHERE table_schema=current_schema() "
                                                            "AND table_name = ANY(%s)", (["access_profiles", "access_profile_perms", "org_features", "setup_changes"],))}
    assert not set(db.DELETE_TABLES) & {"access_profiles", "access_profile_perms", "org_features", "setup_changes"}, "조직 데이터 — 계정 삭제 대상 아님"
    print("OK — A 스키마 멱등 · 기본 프로필 2 · 권한 시드 한 번 · role=admin 이관 · user_id 열 없음")


def test_judge(admin, a, b):
    custom = features.profile_clone(admin, "standard_user", f"웹대화 없음 {TAG}", "합성")["id"]
    features.profile_update(admin, custom, f"웹대화 없음 {TAG}", "합성", set(features.PROFILE_FEATURES) - {"webchat", "trash"})
    features.user_profile_set(admin, b, custom)
    setenv(WEBCHAT_ENABLED=None, TRASH_ENABLED=None, DOWNLOAD_PUBLIC=None)
    # 행 없음 = env == "1"(옛 의미)
    sql("DELETE FROM org_features WHERE feature IN ('webchat','download_public')")
    features.clear_cache()
    assert not features.feature_on(a, "webchat")
    setenv(WEBCHAT_ENABLED="1")
    assert features.feature_on(a, "webchat") and not features.feature_on(b, "webchat"), "행 없음 + env 1 = 켜짐(프로필은 본다)"
    # 조직 꺼짐 = 꺼짐(env 1 이어도)
    org("webchat", False)
    assert not features.feature_on(a, "webchat") and not features.feature_on(admin, "webchat"), "조직 꺼짐 = 프로필과 상관없이 꺼짐(P5)"
    # 조직 켜짐 + 프로필 권한 없음 = 꺼짐 · 둘 다 = 켜짐 · 시스템 관리자 = 전부
    org("webchat", True)
    setenv(WEBCHAT_ENABLED=None)
    assert features.feature_on(a, "webchat") and features.feature_on(admin, "webchat") and not features.feature_on(b, "webchat")
    # env 0(그리고 1·빈 값이 아닌 값) = 비상 끄기
    for v in ("0", "false"):
        setenv(WEBCHAT_ENABLED=v)
        assert not features.feature_on(a, "webchat") and not features.feature_on(admin, "webchat"), v
    setenv(WEBCHAT_ENABLED="1")
    assert features.feature_on(a, "webchat"), "env 1 = 조직 설정을 따른다"
    # uid 없음 = 조직만(정리 작업·CLI)
    assert features.feature_on(None, "webchat")
    # 조직 범위 기능은 프로필을 보지 않는다
    org("download_public", True)
    assert features.feature_on(b, "download_public") and features.feature_on(None, "download_public")
    try:
        features.feature_on(a, "nope")
        raise AssertionError("모르는 기능은 ValueError")
    except ValueError:
        pass
    # 기존 경로가 프로필을 본다 — 휴지통·작업·웹 대화
    org("trash", True)
    org("converse", True)
    assert db.trash_on(a) and not db.trash_on(b) and db.trash_on(), "trash_on(uid) = 프로필까지 · uid 없으면 조직만"
    assert db.job_switch_on("converse", a) and db.job_switch_on("converse", b)
    assert webchat.enabled(a) and not webchat.enabled(b) and webchat.enabled()
    org("chat_mcp", True)
    assert webchat.chat_mcp_enabled(a) and not webchat.chat_mcp_enabled(b), "도구 호출 = 웹 대화 + 대화 도구 호출 둘 다"
    acc = features.access_of(b)
    assert acc["profile"] == f"웹대화 없음 {TAG}" and "webchat" not in acc["features"] and "converse" in acc["features"], acc
    # 캐시: 다른 프로세스가 바꾼 값은 CACHE_SECONDS 안에 반영 — 같은 프로세스 저장은 즉시
    features.org_set(admin, "webchat", False)
    assert not webchat.enabled(a), "관리자 저장은 다음 요청부터 바로"
    features.org_set(admin, "webchat", True)
    print("OK — B 판정(조직×프로필×env 비상 끄기 · 행 없음 = env · uid 없음 = 조직만) · trash_on·job_switch_on·webchat 이 프로필을 본다")
    return custom


def test_seed(admin):
    sql("DELETE FROM org_features")
    setenv(TRASH_ENABLED="1", WEBCHAT_ENABLED=None, IMPORTS_ENABLED="0")
    got = features.seed_org_from_env()
    assert set(got) == {f.key for f in features.FEATURES}, got
    rows = {r["feature"]: r["enabled"] for r in sql("SELECT feature,enabled FROM org_features")}
    assert rows["trash"] is True and rows["webchat"] is False and rows["imports"] is False, rows
    setenv(TRASH_ENABLED=None, WEBCHAT_ENABLED="1")
    assert features.seed_org_from_env() == [], "두 번째 시작은 덮어쓰지 않는다"
    rows = {r["feature"]: r["enabled"] for r in sql("SELECT feature,enabled FROM org_features")}
    assert rows["trash"] is True and rows["webchat"] is False, rows
    assert not features.feature_on(admin, "webchat"), "시드 뒤 env 1 은 조직 설정을 따른다(꺼짐)"
    assert db.trash_on(admin), "env 비어도 조직 켜짐이면 켜짐"
    seed = changes_for("trash")
    assert seed and seed[-1]["kind"] == "seed" and seed[-1]["to_val"] == {"enabled": True} and seed[-1]["actor_id"] is None
    setenv(TRASH_ENABLED=None, WEBCHAT_ENABLED=None, IMPORTS_ENABLED=None)
    print("OK — C 초기값 = 첫 시작 env 값 · 두 번째 시작 덮어쓰기 없음 · 변경 기록 seed")


def test_guard(admin, a, custom):
    expect("FORBIDDEN", features.org_set, a, "trash", False)
    expect("FORBIDDEN", features.user_profile_set, a, a, "system_admin")
    expect("FORBIDDEN", features.profile_clone, a, "standard_user", "x" + TAG)
    expect("FORBIDDEN", features.profile_update, a, custom, "x", "", [])
    expect("FORBIDDEN", features.profile_delete, a, custom)
    for fn, args in ((admin_db.profiles, ()), (admin_db.org_features, ()), (admin_db.setup_changes, ()), (admin_db.user_profiles, ()),
                     (admin_db.org_feature_set, (admin, "trash", False)), (admin_db.user_profile_set, (admin, a, "system_admin"))):
        expect("FORBIDDEN", fn, "user", *args)
    # 보호
    sole = sql("SELECT id FROM users WHERE profile_id='system_admin'")
    assert [r["id"] for r in sole] == [admin], sole
    expect("LAST-ADMIN", features.user_profile_set, admin, admin, "standard_user")
    expect("PROFILE-BUILTIN", features.profile_delete, admin, "standard_user")
    expect("PROFILE-BUILTIN", features.profile_delete, admin, "system_admin")
    expect("PROFILE-IN-USE", features.profile_delete, admin, custom)
    expect("PROFILE-FIXED", features.profile_update, admin, "system_admin", "시스템 관리자", "x", ["trash"])
    expect("PROFILE-NAME-TAKEN", features.profile_clone, admin, "standard_user", "표준 사용자")
    expect("ARG-INVALID", features.profile_update, admin, custom, "x", "", ["root"])
    expect("ARG-INVALID", features.profile_clone, admin, "standard_user", "  ")
    expect("NOT-FOUND", features.user_profile_set, admin, a, "p_nope")
    expect("ARG-INVALID", features.org_set, admin, "nope", True)
    print("OK — D·E 관리자만(FORBIDDEN · admin_db 조회자) · 마지막 시스템 관리자 · 기본·사용 중 삭제 거절 · 시스템 관리자 권한 고정")


def test_changes_and_legacy(admin, a, b, custom):
    # 사용자 지정 → 해제(관리자를 잃으면 웹 세션 끊기 · role 거울)
    out = features.user_profile_set(admin, a, "system_admin")
    assert out["changed"] and sql("SELECT role FROM users WHERE id=%s", (a,))[0]["role"] == "admin"
    features.user_profile_set(admin, a, "standard_user")
    r = sql("SELECT role,profile_id,web_revoked_before FROM users WHERE id=%s", (a,))[0]
    assert r["role"] == "user" and r["profile_id"] == "standard_user" and r["web_revoked_before"] is not None
    ch = changes_for(a)
    assert [(x["kind"], x["from_val"], x["to_val"]) for x in ch[-2:]] == [
        ("user_profile", {"profile": "standard_user"}, {"profile": "system_admin"}),
        ("user_profile", {"profile": "system_admin"}, {"profile": "standard_user"})] and ch[-1]["actor_id"] == admin
    # admin_act 부여·회수(Administration 화면) = 프로필 지정 · 옛 감사도 그대로
    db.admin_act(admin, "role", b, "admin")
    assert sql("SELECT role,profile_id FROM users WHERE id=%s", (b,))[0] == {"role": "admin", "profile_id": "system_admin"}
    db.admin_act(admin, "role", b, "user")
    assert sql("SELECT role,profile_id FROM users WHERE id=%s", (b,))[0] == {"role": "user", "profile_id": "standard_user"}
    expect("LAST-ADMIN", db.admin_act, admin, "role", admin, "user")
    # admin_recover(CLI 복구) = 시스템 관리자
    c = user("recover")
    db.admin_recover(f"recover-{TAG}@example.com")
    assert sql("SELECT role,profile_id FROM users WHERE id=%s", (c,))[0] == {"role": "admin", "profile_id": "system_admin"}
    db.admin_act(admin, "role", c, "user")
    # 프로필 이름·권한·삭제 기록
    features.profile_update(admin, custom, f"웹대화 없음2 {TAG}", "설명 바꿈", set(features.PROFILE_FEATURES) - {"webchat"})
    kinds = [(x["kind"], x["from_val"], x["to_val"]) for x in changes_for(custom)]
    assert kinds[0][0] == "profile_create" and kinds[0][2]["from"] == "standard_user"
    assert ("profile_update", {"name": f"웹대화 없음 {TAG}", "description": "합성"}, {"name": f"웹대화 없음2 {TAG}", "description": "설명 바꿈"}) in kinds
    assert any(k == "profile_perm" and "trash" not in f["perms"] and "trash" in t["perms"] for k, f, t in kinds)
    features.org_set(admin, "trash", False)
    ch = changes_for("trash")[-1]
    assert (ch["kind"], ch["from_val"], ch["to_val"], ch["actor_id"]) == ("org_feature", {"enabled": True}, {"enabled": False}, admin)
    assert features.org_set(admin, "trash", False) == {"changed": False}, "같은 값은 기록 없음"
    features.user_profile_set(admin, b, "standard_user")
    features.profile_delete(admin, custom)
    assert changes_for(custom)[-1]["kind"] == "profile_delete" and not sql("SELECT 1 FROM access_profiles WHERE id=%s", (custom,))
    rows = features.changes()
    assert rows and {"at", "actor_email", "kind", "subject", "from_val", "to_val"} <= set(rows[0])
    print("OK — F 변경 기록(사용자 지정·이름·권한·조직·삭제, 전·후) · G admin_act·admin_recover = 프로필 지정 · 회수 = 웹 세션 끊기")


async def test_http(admin, a):
    site = main.site
    site.dev, site.dev_user = False, ""
    site.secret = site.secret or secrets.token_bytes(32)   # 세션 쿠키 서명용(시험 전용 값)

    def client(uid=None):
        h = httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url=PUBLIC)
        if uid:
            h.cookies.set("crm_session", site.session_value(uid))
        return h
    gets = ("/admin/profiles", "/admin/profiles/standard_user", "/admin/profiles/standard_user?edit=1", "/admin/profiles/system_admin?edit=1",
            "/admin/features", "/admin/changes", "/admin/users")
    async with client() as h0, client(a) as ha, client(admin) as hz:
        for path in gets:
            for h in (h0, ha):
                r = await h.get(path)
                assert r.status_code == 404 and "<" not in r.text, (path, r.status_code)
            r = await hz.get(path)
            assert r.status_code == 200, (path, r.status_code, r.text[:300])
            t = r.text
            assert "<script" not in t.lower() and not re.search(r"\son[a-z]+\s*=", t, re.I), (path, "스크립트·이벤트 속성 0")
            assert "script-src 'self'" in r.headers["content-security-policy"] and r.headers["cache-control"] == "no-store", path
            assert t.count("<table") == len(re.findall(r'<div class="tbl(?: fit)?"><table>', t)), (path, "표는 가로 스크롤 래퍼 안")
        assert (await hz.get("/admin/profiles/p_nope")).status_code == 404
        assert (await hz.get("/admin/profiles?x=1")).status_code == 400
        assert (await hz.get("/admin/profiles/standard_user?edit=2")).status_code == 400
        t = (await hz.get("/admin/profiles/system_admin?edit=1")).text
        assert t.count(" disabled") == len(features.PROFILE_FEATURES) and "바꿀 수 없어요" in t
        t = (await hz.get("/admin/profiles/standard_user")).text
        assert "기본 프로필은 지울 수 없어요" in t and 'href="/admin/profiles/standard_user?edit=1"' in t
        ok = {"origin": PUBLIC}
        FORM = {**ok, "content-type": "application/x-www-form-urlencoded"}   # 브라우저 빈 form(삭제 버튼) 그대로
        # 비관리자 POST = 404 · Origin 403 · form 400
        for path, data in (("/admin/features/trash", {"enabled": "1"}), ("/admin/users/profile", {"user": site._opaque(a), "profile": "system_admin"}),
                           ("/admin/profiles/new", {"src": "standard_user", "name": "x"})):
            assert (await ha.post(path, headers=ok, data=data)).status_code == 404, path
            r = await hz.post(path, headers={"origin": "https://evil.example"}, data=data)
            assert r.status_code == 403 and "ORIGIN" in r.text, path
            assert (await hz.post(path, headers=ok, json=data)).status_code == 400, path
        assert (await hz.post("/admin/features/trash", headers=ok, data={"enabled": "2"})).status_code == 400
        assert (await hz.post("/admin/features/nope", headers=ok, data={"enabled": "1"})).status_code == 400
        # 조직 켜기 · 복제 · 권한 저장 · 사용자 지정 · 삭제
        r = await hz.post("/admin/features/trash", headers=ok, data={"enabled": "1"})
        assert r.status_code == 303 and r.headers["location"] == "/admin/features" and db.trash_on(a)
        r = await hz.post("/admin/profiles/new", headers=ok, data={"src": "standard_user", "name": f"화면 {TAG}", "description": "합성"})
        assert r.status_code == 303 and r.headers["location"].startswith("/admin/profiles/p_"), (r.status_code, r.text[:200])
        pid = r.headers["location"].rsplit("/", 1)[1]
        form = {"name": f"화면 {TAG}", "description": "합성", **{f"perm_{k}": "1" for k in features.PROFILE_FEATURES if k != "trash"}}
        r = await hz.post(f"/admin/profiles/{pid}/save", headers=ok, data=form)
        assert r.status_code == 303 and "trash" not in features.profile_detail(pid)["perms"]
        r = await hz.post("/admin/users/profile", headers=ok, data={"user": site._opaque(a), "profile": pid})
        assert r.status_code == 303 and not db.trash_on(a), "사용자 프로필 바꾸기 = 다음 요청부터"
        r = await hz.post(f"/admin/profiles/{pid}/delete", headers=FORM, content=b"")
        assert r.status_code == 409 and "PROFILE-IN-USE" in r.text
        r = await hz.post("/admin/users/profile", headers=ok, data={"user": site._opaque(admin), "profile": "standard_user"})
        assert r.status_code == 409 and "LAST-ADMIN" in r.text
        await hz.post("/admin/users/profile", headers=ok, data={"user": site._opaque(a), "profile": "standard_user"})
        r = await hz.post(f"/admin/profiles/{pid}/delete", headers=FORM, content=b"")
        assert r.status_code == 303 and r.headers["location"] == "/admin/profiles"
        t = (await hz.get("/admin/changes")).text
        assert "사용자 프로필 지정" in t and "조직 기능 설정" in t and "프로필 삭제" in t and f"a-{TAG}@example.com" in t
        os.environ["CRM_TRASH_ENABLED"] = "0"
        t = (await hz.get("/admin/features")).text
        assert "환경변수로 꺼짐" in t and not db.trash_on(a), "env 0 = 비상 끄기(화면에 보인다)"
        os.environ.pop("CRM_TRASH_ENABLED", None)
        t = (await hz.get("/admin/users")).text
        assert 'action="/admin/users/profile"' in t and "<th>프로필</th>" in t and a not in t and admin not in t, "내부 id 0(불투명 id 만)"
        r = await hz.post("/admin/users/profile", headers=ok, data={"user": "nope", "profile": "standard_user"})
        assert r.status_code == 404 and "NOT-FOUND" in r.text
    print("OK — H 화면 GET 200(관리자)·404(무세션·일반) · 스크립트 0 · POST 사다리(404·403·400) · 복제·저장·조직·사용자 지정·삭제 303")


def test_static():
    src = (HERE / "admin_profiles_web.py").read_text(encoding="utf-8")
    used_db = set(re.findall(r"\bdb\.(\w+)", src))
    assert used_db <= {"CrmError"}, ("화면 모듈은 db 조회를 직접 안 부른다", used_db)
    used_f = set(re.findall(r"\bfeatures\.(\w+)", src))
    assert used_f <= {"BY_KEY", "PROFILE_FEATURES", "SYSTEM_ADMIN", "STANDARD_USER", "NAME_MAX", "DESC_MAX", "CACHE_SECONDS", "CHANGES_LIST"}, \
        ("화면 모듈은 features 의 상수만 — 읽기·쓰기는 admin_db 경유", used_f)
    left = []
    for p in sorted(HERE.glob("*.py")):
        if p.name.startswith("test_") or p.name in ("features.py", "envnames.py"):
            continue
        t = p.read_text(encoding="utf-8")
        left += [f"{p.name}: {m}" for m in re.findall(r"switch_on\(\"\w+\"\)|env\(\"(?:\w+_ENABLED|DOWNLOAD_PUBLIC)\"", t)]
    assert not left, ("스위치를 직접 읽는 자리가 남았다 — features.feature_on 으로", left)
    print("OK — 정적: 화면 모듈 = admin_db 만 · 스위치 직접 읽기 0(판정은 features.feature_on 하나)")


def main_():
    for k in ENVS:
        os.environ.pop(k, None)
    db.init_schema()
    # 전용 시험 DB — 조직 설정·시스템 관리자 지정을 비운다(재실행 가능)
    sql("DELETE FROM org_features")
    sql("UPDATE users SET profile_id=NULL, role='user' WHERE profile_id IS NOT NULL OR role='admin'")
    sql("DELETE FROM access_profiles WHERE NOT builtin")
    features.clear_cache()
    admin = user("admin")
    with db.tx() as c:
        features.assign_in(c, None, admin, features.SYSTEM_ADMIN)
    a, b = user("a"), user("b")
    try:
        test_static()
        test_schema(admin)
        custom = test_judge(admin, a, b)
        test_seed(admin)
        test_guard(admin, a, custom)
        test_changes_and_legacy(admin, a, b, custom)
        asyncio.run(test_http(admin, a))
    finally:
        for k in ENVS:
            os.environ.pop(k, None)
        db.close()
    print("모두 통과")


if __name__ == "__main__":
    main_()
