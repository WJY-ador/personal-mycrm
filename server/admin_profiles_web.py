"""관리자 화면 — Profiles · Feature Settings · Setup Audit Trail · 사용자 프로필 바꾸기(2026-11-12, Salesforce Setup 꼴).

/admin 규칙 그대로: 서버 렌더 + form POST 만(스크립트 0) · 비관리자·무세션·DEV 404 · POST 는 Origin 정확히 일치(403) · form 4KB(400) ·
DB 접근은 admin_db 만(조회자 확인 → features). 동적 값은 전부 web._esc. 오류 화면은 코드와 문구만(입력을 되비추지 않는다).
"""
from urllib.parse import quote

from starlette.concurrency import run_in_threadpool
from starlette.responses import RedirectResponse

import admin_db
import db
import features

KIND_LABELS = {"seed": "초기값(환경변수에서)", "org_feature": "조직 기능 설정", "profile_create": "프로필 만들기",
               "profile_update": "프로필 이름·설명", "profile_perm": "프로필 기능 권한", "profile_delete": "프로필 삭제",
               "user_profile": "사용자 프로필 지정"}
TAG_BUILTIN, TAG_CUSTOM = '<span class="tag">기본</span>', '<span class="tag int">사용자 지정</span>'
ERR_STATUS = {"NOT-FOUND": 404, "FORBIDDEN": 403, "LAST-ADMIN": 409, "PROFILE-BUILTIN": 409, "PROFILE-IN-USE": 409,
              "PROFILE-NAME-TAKEN": 409, "PROFILE-FIXED": 409}


def _w():
    import web   # web 이 이 모듈을 부른다 — 부를 때 가져온다
    return web


def _btn(action, label, fields=None, danger=False):
    w = _w()
    hidden = "".join(f'<input type="hidden" name="{w._esc(k)}" value="{w._esc(v)}">' for k, v in (fields or {}).items())
    return (f'<form method="post" action="{w._esc(action)}">{hidden}'
            f'<button type="submit"{" class=danger" if danger else ""}>{w._esc(label)}</button></form>')


def _perm_label(key):
    return features.BY_KEY[key].label


def _pid_href(pid):
    return "/admin/profiles/" + quote(pid, safe="")


def _profile_options(rows, cur):
    w = _w()
    return "".join(f'<option value="{w._esc(p["id"])}"{" selected" if p["id"] == cur else ""}>{w._esc(p["name"])}</option>' for p in rows)


async def _who(site, request):
    uid = await site._admin_who(request)
    return uid


async def _post(site, request, back, cur, fn):
    """POST 공통 사다리 — 관리자(404) → Origin(403) → form(400) → fn(form) (CrmError → 상태 코드) → 303 back."""
    w = _w()
    uid = await _who(site, request)
    if uid is None:
        return w._not_found()
    link = f'<p><a href="{w._esc(back)}">돌아가기</a></p>'
    if not site.same_origin(request):
        return w._admin_page("다른 사이트에서 온 요청이에요", f"<h1>다른 사이트에서 온 요청이에요</h1><p>ORIGIN</p>{link}", 403, cur=cur)
    form = await site._admin_form(request)
    if form is None:
        return w._admin_page("요청이 틀렸어요", f"<h1>요청이 틀렸어요</h1><p>ARG-INVALID</p>{link}", 400, cur=cur)
    try:
        dest = await run_in_threadpool(fn, uid, request.state.role, form)
    except db.CrmError as e:
        act = f"<p>{w._esc(e.action)}</p>" if e.action else ""
        return w._admin_page("처리하지 못했어요", f"<h1>처리하지 못했어요</h1><p>{w._esc(e.code)} — {w._esc(e.message)}</p>{act}{link}",
                             ERR_STATUS.get(e.code, 400), cur=cur)
    return RedirectResponse(dest or back, status_code=303)


def _need(form, *keys):
    if any(k not in form for k in keys):
        raise db.CrmError("ARG-INVALID", "요청이 틀렸어요.")


# ── Profiles ─────────────

async def profiles(site, request):
    w = _w()
    if await _who(site, request) is None:
        return w._not_found()
    if request.query_params:
        return site._admin_bad("프로필을 열 수 없어요", "쿼리 키를 받지 않아요.", "/admin/profiles", "profiles")
    rows = await run_in_threadpool(admin_db.profiles, request.state.role)
    n = len(features.PROFILE_FEATURES)
    trs = [f'<tr><td><a href="{w._esc(_pid_href(p["id"]))}">{w._esc(p["name"])}</a></td>'
           f'<td>{TAG_BUILTIN if p["builtin"] else TAG_CUSTOM}</td>'
           f'<td class="long">{w._esc(p["description"]) or "<span class=muted>—</span>"}</td>'
           f'<td class="num">{w._esc(len(p["perms"]))}/{n}</td><td class="num">{w._esc(p["users"])}</td>'
           f'<td>{w._esc(w._kst(p["updated"]))}</td></tr>' for p in rows]
    new = (f'<form class="rq" method="post" action="/admin/profiles/new"><label>복제할 프로필<select name="src">'
           f'{_profile_options(rows, features.STANDARD_USER)}</select></label>'
           f'<label>새 이름<input name="name" maxlength="{features.NAME_MAX}" required></label>'
           f'<label>설명<input name="description" maxlength="{features.DESC_MAX}"></label><button type="submit">새 프로필 만들기</button></form>')
    body = (f'<div class="hdr"><div><p class="eyebrow">Setup</p><h1>프로필 {len(rows)}개</h1></div></div>'
            f'<p class="note">사용자마다 프로필 하나예요. 프로필은 쓸 수 있는 기능 권한 묶음이에요. 기능은 조직 기능 설정이 켜져 있고 '
            f'프로필에 권한이 있을 때만 열려요. 관리자 화면은 시스템 관리자 프로필만 써요.</p>'
            f'<h2 class="sec">새 프로필</h2><p class="note">기존 프로필을 복제해 만들어요. 권한 체크를 그대로 가져와요(시스템 관리자를 복제해도 관리자 화면은 따라오지 않아요).</p>{new}'
            f'<h2 class="sec">모든 프로필</h2>'
            + w._table(['<th>프로필 이름</th><th>종류</th><th>설명</th><th class="num">기능 권한</th><th class="num">사용자</th><th>마지막 수정</th>'], trs))
    return w._admin_page("관리 — 프로필", body, cur="profiles")


async def profile(site, request):
    w = _w()
    if await _who(site, request) is None:
        return w._not_found()
    pid = request.path_params["pid"]
    q = dict(request.query_params)
    if set(q) - {"edit"} or q.get("edit", "1") != "1":
        return site._admin_bad("프로필을 열 수 없어요", "쿼리 키는 edit=1 하나만 받아요.", "/admin/profiles", "profiles")
    try:
        p, org = await run_in_threadpool(lambda: (admin_db.profile_detail(request.state.role, pid), admin_db.org_features(request.state.role)))
    except db.CrmError as e:
        if e.code != "NOT-FOUND":
            raise
        return w._admin_page("프로필을 찾지 못했어요", '<h1>프로필을 찾지 못했어요</h1><p>NOT-FOUND</p><p><a href="/admin/profiles">프로필 목록으로</a></p>',
                             404, cur="profiles")
    edit, fixed = "edit" in q, p["id"] == features.SYSTEM_ADMIN
    href = _pid_href(p["id"])
    orgon = {r["feature"].key: r["effective"] for r in org}
    crumbs = [("프로필", "/admin/profiles"), (p["name"], None)]
    kind = "기본 프로필" if p["builtin"] else "사용자 지정 프로필"
    perms = set(p["perms"])
    if edit:
        trs = []
        for k in features.PROFILE_FEATURES:
            f = features.BY_KEY[k]
            box = (f'<input type="checkbox" id="perm_{w._esc(k)}" name="perm_{w._esc(k)}" value="1"{" checked" if k in perms else ""}'
                   f'{" disabled" if fixed else ""}>')
            trs.append(f'<tr><td class="ck">{box}</td><td><label for="perm_{w._esc(k)}">{w._esc(f.label)}</label></td>'
                       f'<td class="long note">{w._esc(f.note)}</td></tr>')
        fixed_note = '<p class="note warn">시스템 관리자는 모든 기능 권한을 가져요. 체크는 바꿀 수 없어요.</p>' if fixed else ""
        body = (f'<div class="hdr"><div><p class="eyebrow">프로필 편집</p><h1>{w._esc(p["name"])}</h1></div></div>'
                f'<form class="pf" method="post" action="{w._esc(href)}/save">'
                f'<div class="acts top"><button type="submit" class="primary">저장</button><a class="btn" href="{w._esc(href)}">취소</a></div>'
                f'<h2 class="sec">프로필 상세</h2><div class="fields">'
                f'<label>프로필 이름<input name="name" value="{w._esc(p["name"])}" maxlength="{features.NAME_MAX}" required></label>'
                f'<label>설명<textarea name="description" rows="2" maxlength="{features.DESC_MAX}">{w._esc(p["description"])}</textarea></label></div>'
                f'<h2 class="sec">기능 권한</h2>{fixed_note}'
                + w._table(['<th class="ck">켬</th><th>기능</th><th>설명</th>'], trs)
                + f'<div class="acts bottom"><button type="submit" class="primary">저장</button><a class="btn" href="{w._esc(href)}">취소</a></div></form>')
        return w._admin_page(f"관리 — {p['name']} 편집", body, cur="profiles", crumbs=crumbs)
    trs = []
    for k in features.PROFILE_FEATURES:
        f = features.BY_KEY[k]
        mark = '<span class="yes" aria-label="있음">✓</span>' if k in perms else '<span class="muted" aria-label="없음">—</span>'
        st = '<span class="tag on">켜짐</span>' if orgon.get(k) else '<span class="tag">꺼짐</span>'
        trs.append(f'<tr><td class="ck">{mark}</td><td>{w._esc(f.label)}</td><td class="long note">{w._esc(f.note)}</td><td>{st}</td></tr>')
    urows = [f'<tr><td class="email">{w._esc(u["email"])}</td><td>'
             + ('<span class="tag blocked">차단</span>' if u["blocked_at"] else "")
             + ('<span class="tag deleted">삭제됨</span>' if u["status"] == "deleted" else "") + '</td></tr>' for u in p["users"]]
    can_del = not p["builtin"] and not p["users"]
    why = "기본 프로필은 지울 수 없어요." if p["builtin"] else f"사용자 {len(p['users'])}명이 쓰고 있어 지울 수 없어요." if p["users"] else ""
    acts = (f'<a class="btn primary" href="{w._esc(href)}?edit=1">편집</a>'
            + (_btn(f"{href}/delete", "삭제", danger=True) if can_del else f'<span class="note">{w._esc(why)}</span>'))
    body = (f'<div class="hdr"><div><p class="eyebrow">프로필</p><h1>{w._esc(p["name"])}</h1></div><div class="acts">{acts}</div></div>'
            f'<h2 class="sec">프로필 상세</h2><dl class="meta"><dt>프로필 이름</dt><dd>{w._esc(p["name"])}</dd>'
            f'<dt>설명</dt><dd>{w._esc(p["description"]) or "—"}</dd><dt>종류</dt><dd>{kind}</dd>'
            f'<dt>관리자 화면</dt><dd>{"있음" if fixed else "없음"}</dd></dl>'
            f'<h2 class="sec">기능 권한</h2><p class="note">조직 열 = 지금 조직 기능 설정(환경변수 비상 끄기 포함). 둘 다 켜져야 그 사용자에게 열려요.</p>'
            + w._table(['<th class="ck">권한</th><th>기능</th><th>설명</th><th>조직</th>'], trs)
            + f'<h2 class="sec">이 프로필의 사용자 {len(p["users"])}명</h2><p class="note">프로필은 <a href="/admin/users">사용자</a>에서 바꿔요.</p>'
            + w._table(['<th>이메일</th><th>상태</th>'], urows, "이 프로필을 쓰는 사용자가 없어요"))
    return w._admin_page(f"관리 — {p['name']}", body, cur="profiles", crumbs=crumbs)


async def profile_new(site, request):
    def run(uid, role, form):
        _need(form, "src", "name")
        out = admin_db.profile_clone(role, uid, form["src"], form["name"], form.get("description", ""))
        return _pid_href(out["id"])
    return await _post(site, request, "/admin/profiles", "profiles", run)


async def profile_save(site, request):
    pid = request.path_params["pid"]

    def run(uid, role, form):
        _need(form, "name")
        perms = {k[5:] for k, v in form.items() if k.startswith("perm_") and v == "1"}
        if pid == features.SYSTEM_ADMIN:   # 고정 — 비활성 체크는 전송되지 않는다
            perms = set(features.PROFILE_FEATURES)
        admin_db.profile_update(role, uid, pid, form["name"], form.get("description", ""), perms)
        return _pid_href(pid)
    return await _post(site, request, _pid_href(pid), "profiles", run)


async def profile_delete(site, request):
    pid = request.path_params["pid"]

    def run(uid, role, form):
        admin_db.profile_delete(role, uid, pid)
        return "/admin/profiles"
    return await _post(site, request, _pid_href(pid), "profiles", run)


async def user_profile(site, request):
    def run(uid, role, form):
        _need(form, "user", "profile")   # user = 불투명 id(HMAC) — Users 화면은 내부 id 를 내보내지 않는다
        target = next((u["id"] for u in admin_db.users(role) if site._opaque(u["id"]) == form["user"]), None)
        if target is None:
            raise db.CrmError("NOT-FOUND", "그 계정을 찾지 못했어요.", "새로 고침한 뒤 다시 해 보세요.")
        admin_db.user_profile_set(role, uid, target, form["profile"])
        return "/admin/users"
    return await _post(site, request, "/admin/users", "users", run)


def users_cell(rows, cur, oid):
    """Users 목록의 프로필 칸 — 선택 + [바꾸기](form POST /admin/users/profile). oid = 불투명 id(내부 id 를 화면에 두지 않는다)."""
    w = _w()
    return (f'<form class="inline" method="post" action="/admin/users/profile"><input type="hidden" name="user" value="{w._esc(oid)}">'
            f'<select name="profile" aria-label="프로필">{_profile_options(rows, cur)}</select><button type="submit">바꾸기</button></form>')


# ── Feature Settings ─────────────

async def org_features(site, request):
    w = _w()
    if await _who(site, request) is None:
        return w._not_found()
    if request.query_params:
        return site._admin_bad("조직 기능 설정을 열 수 없어요", "쿼리 키를 받지 않아요.", "/admin/features", "features")
    rows = await run_in_threadpool(admin_db.org_features, request.state.role)
    envlbl = {"": "비어 있음", "on": "1", "off": "비상 끄기"}
    groups = (("profile", "사용자 기능 — 조직 설정 + 프로필 권한"), ("org", "조직 기능 — 조직 설정만"))
    out = []
    for scope, title in groups:
        trs = []
        for r in rows:
            f = r["feature"]
            if f.scope != scope:
                continue
            state = '<span class="tag on">켜짐</span>' if r["org"] else '<span class="tag">꺼짐</span>'
            if r["env"] == "off":
                state += ' <span class="tag over">환경변수로 꺼짐</span>'
            act = _btn(f"/admin/features/{f.key}", "끄기" if r["org"] else "켜기", {"enabled": "0" if r["org"] else "1"}, danger=r["org"])
            trs.append(f'<tr><td>{w._esc(f.label)}</td><td class="long note">{w._esc(f.note)}</td><td>{state}</td>'
                       f'<td><span class="api">CRM_{w._esc(f.env)}</span> <span class="note">{w._esc(envlbl[r["env"]])}</span></td>'
                       f'<td>{act}</td></tr>')
        out.append(f'<h2 class="sec">{w._esc(title)}</h2>'
                   + w._table(['<th>기능</th><th>설명</th><th>조직 설정</th><th>환경변수(비상 끄기)</th><th>동작</th>'], trs))
    body = (f'<div class="hdr"><div><p class="eyebrow">Setup</p><h1>조직 기능 설정</h1></div></div>'
            f'<p class="note">기능마다 조직 전체 켜짐·꺼짐이에요. 바꾸면 다음 요청부터 바로 적용돼요(재배포 없음, 서버 캐시 {features.CACHE_SECONDS}초 이내). '
            f'환경변수는 비상 끄기로만 남아요 — 값이 0이면 여기 설정과 상관없이 꺼져요. 사용자 기능은 프로필 권한도 있어야 열려요.</p>'
            + "".join(out))
    return w._admin_page("관리 — 조직 기능 설정", body, cur="features")


async def org_feature_set(site, request):
    key = request.path_params["key"]

    def run(uid, role, form):
        _need(form, "enabled")
        if form["enabled"] not in ("0", "1"):
            raise db.CrmError("ARG-INVALID", "요청이 틀렸어요.")
        admin_db.org_feature_set(role, uid, key, form["enabled"] == "1")
        return "/admin/features"
    return await _post(site, request, "/admin/features", "features", run)


# ── Setup Audit Trail ─────────────

def _val(kind, v):
    if v is None:
        return "—"
    if "enabled" in v:
        return "켜짐" if v["enabled"] else "꺼짐"
    if "perms" in v and "name" not in v:
        return ", ".join(_perm_label(k) for k in v["perms"] if k in features.BY_KEY) or "없음"
    if "profile" in v:
        return v["profile"]
    parts = [v.get("name") or ""]
    if v.get("description"):
        parts.append(v["description"])
    if "from" in v:
        parts.append(f"복제: {v['from']}")
    if "perms" in v:
        parts.append("권한 " + str(len(v["perms"])) + "개")
    return " · ".join(p for p in parts if p)


async def changes(site, request):
    w = _w()
    if await _who(site, request) is None:
        return w._not_found()
    if request.query_params:
        return site._admin_bad("변경 기록을 열 수 없어요", "쿼리 키를 받지 않아요.", "/admin/changes", "changes")
    role = request.state.role
    rows, profs = await run_in_threadpool(lambda: (admin_db.setup_changes(role), admin_db.profiles(role)))
    pname = {p["id"]: p["name"] for p in profs}

    def subject(r):
        if r["kind"] in ("seed", "org_feature"):
            f = features.BY_KEY.get(r["subject"])
            return w._esc(f.label if f else r["subject"])
        if r["kind"] == "user_profile":
            return f'<span class="email">{w._esc(r["target_email"] or r["subject"][:8])}</span>'
        name = r["profile_name"] or (r["from_val"] or {}).get("name") or r["subject"]
        return w._esc(name)

    def pv(r, v):
        if r["kind"] == "user_profile" and v:
            return w._esc(pname.get(v["profile"], v["profile"]))
        return w._esc(_val(r["kind"], v))
    trs = [f'<tr><td>{w._esc(w._kst(r["at"]))}</td><td class="email">{w._esc(r["actor_email"]) if r["actor_email"] else "<span class=muted>시스템</span>"}</td>'
           f'<td>{w._esc(KIND_LABELS.get(r["kind"], r["kind"]))}</td><td>{subject(r)}</td><td class="long">{pv(r, r["from_val"])}</td>'
           f'<td class="long">{pv(r, r["to_val"])}</td></tr>' for r in rows]
    body = (f'<div class="hdr"><div><p class="eyebrow">Setup</p><h1>변경 기록</h1></div></div>'
            f'<p class="note">조직 기능 설정 · 프로필 · 사용자 프로필 지정을 누가, 언제, 무엇을 바꿨는지 최근 {features.CHANGES_LIST}건을 보여요. '
            f'관리자 부여·차단 같은 계정 동작은 <a href="/admin/setup">Administration</a> 감사 로그에 있어요.</p>'
            + w._table(['<th>시각</th><th>실행자</th><th>무엇을</th><th>대상</th><th>전</th><th>후</th>'], trs, "아직 변경 기록이 없어요"))
    return w._admin_page("관리 — 변경 기록", body, cur="changes")
