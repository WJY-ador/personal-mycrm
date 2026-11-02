"""MCP facade — 겉면 5개(find·read·write·decide·purge)로 기존 도구(op)를 부른다. 계획 2026-11-02 「MCP facade(A′)」 §0~§3.

한계(§0): 운영 MCP 는 stateless_http + json_response 라 호출 중 사용자에게 되물을 수 없다. 등급 분리는 보안 게이트가 아니라
편의·가시성 장치다. 실제 안전 = 서버 가드 + 규칙 문장. bind 가 증명하는 것은 「이 대화의 모델이 preview 를 받았다」까지 —
「사용자가 봤다」는 글 규칙이다.

- op = 지금 도구 이름 그대로. op 마다 tier·family 는 mcp_catalog.json 이 정본(설명은 docstring 에서 만든다).
- 같은 guard 를 지난다 — facade 는 SDK 와 같은 입력 모델(서명에서 만든 pydantic)로 검증하고 guard 로 감싼 함수를 같은 스레드에서 부른다.
  경로는 VIA contextvar 로 넘기고, guard 가 사용 집계 키에만 「f:」를 붙인다(write_gate·WRITE_LIMITS 조회 키는 op 그대로).
- 확정·삭제(decide·purge)는 read(op="decide_preview") 가 준 bind 가 있어야 한다. bind = HMAC(key, op ∥ 정규화 params ∥ 대상 스냅샷)
  base64url 앞 16자, key = HMAC(CRM_SESSION_SECRET, "bind-v1"). 무상태·만료 없음 — 대상이 바뀌면 BIND-STALE.
  비밀을 바꾸면 웹 세션과 bind 가 함께 무효가 된다. 이관 op(catalog bind=self)은 자기 바인딩이라 면제.
- main.py 가 맨 끝에서 install(mcp, guard, uid_of, extra_ops) 를 한 번 부른다. 이 모듈은 main 을 import 하지 않는다.
"""
import base64
import contextvars
import difflib
import hashlib
import hmac
import json
import re
from pathlib import Path
from typing import Annotated, Any

import pydantic_core
from pydantic import Field, ValidationError

from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.mcpserver.tools.base import Tool
from mcp_types import CallToolResult, TextContent, ToolAnnotations

import db
from envnames import env

HERE = Path(__file__).resolve().parent
CATALOG_PATH = HERE / "mcp_catalog.json"
TIERS = ("read", "write", "decide", "purge")
SURFACE = TIERS + ("find",)
FIND_MAX = 8
BIND_LEN = 16
PREVIEW = "decide_preview"

# 겉면 래퍼가 꽂는 경로 표식 — "f" = facade 경유. guard 가 사용 집계 키에만 쓴다.
VIA: contextvars.ContextVar = contextvars.ContextVar("crm_via", default="")

COMMON_RULE = "decide_preview 의 shown 을 고치지 않고 그대로 사용자에게 보여 주고, 사용자가 말한 뒤에만 부른다."
PURGE_RULE = "되돌릴 수 없다. 사용자가 분명히 말할 때만."
SELF_RULE = ("이관 op 은 decide_preview·bind 를 쓰지 않는다(자기 바인딩). 반영 전엔 decide_preview 대신 read(op=migration_apply_preview) 결과를 "
             "그대로 사용자에게 보여 주고, 사용자가 말한 뒤에만 부른다.")
_GATE = re.compile(r"때만|뒤에만|전에 부르지 않는다|말하기 전에")


class Op:
    __slots__ = ("name", "tier", "family", "bind", "direct", "tool", "keywords", "examples")

    def __init__(self, name, spec, tool):
        self.name, self.tool = name, tool
        self.tier, self.family = spec["tier"], spec["family"]
        self.bind = spec.get("bind") or ("hmac" if spec["tier"] in ("decide", "purge") else None)
        self.direct = spec.get("direct", True)
        self.keywords, self.examples = list(spec.get("keywords", [])), list(spec.get("examples", []))

    @property
    def doc(self):
        return (self.tool.description or "").strip()

    @property
    def summary(self):
        return self.doc.splitlines()[0].strip() if self.doc else ""


OPS: dict[str, Op] = {}
FAMILIES: list[dict] = []
RULES: dict[str, str] = {}   # op 별 덧붙일 규칙 문장(이관 본체 모듈의 표 — install 이 받는다)
_uid_of = None


def uid_of(ctx):
    """도구 함수가 쓰는 uid 풀기 — main.uid_of 에 위임(install 이 꽂는다). 이관 op(migration_mcp) 도 이걸 쓴다."""
    if _uid_of is None:
        raise RuntimeError("facade.install 전에 불렸어요")
    return _uid_of(ctx)


def load_catalog(path=CATALOG_PATH) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


# ── 오류 ───────────────────────────────────────────────

def error_text(code, message, action="", detail=None) -> str:
    """ToolError 문구 한 꼴 — guard 와 facade 가 같이 쓴다. detail 은 JSON 한 줄로 끝에 붙인다(모델이 읽는다)."""
    out = f"[{code}] {message}" + (f" 다음 조치: {action}" if action else "")
    if detail is not None:
        out += " detail=" + json.dumps(detail, ensure_ascii=False, separators=(",", ":"), default=str)
    return out


def crm_error(code, message, action="", detail=None):
    e = db.CrmError(code, message, action)
    if detail is not None:
        e.detail = detail
    return e


# ── 등록부 ─────────────────────────────────────────────

def ops_of(tier, bind=None):
    return [n for n, o in OPS.items() if o.tier == tier and (bind is None or o.bind == bind)]


def hmac_ops():
    """decide_preview·bind 대상 = D∪P 중 자기 바인딩이 아닌 것."""
    return [n for n, o in OPS.items() if o.bind == "hmac"]


def build_registry(mcp, guard, catalog, extra_ops=()):
    """등록된 직접 도구 + facade 전용 op(guard 로 감싸 Tool 로 만든다) → OPS. 카탈로그와 정확히 같은 op 집합이어야 한다."""
    specs = catalog["ops"]
    tools = {}
    for t in mcp._tool_manager.list_tools():
        if t.name not in SURFACE:
            tools[t.name] = t
    for fn in extra_ops:
        if fn.__name__ in tools:
            raise ValueError(f"facade 전용 op 이 직접 도구와 겹친다: {fn.__name__}")
        tools[fn.__name__] = Tool.from_function(guard(fn), structured_output=None)
    missing, extra = set(tools) - set(specs), set(specs) - set(tools)
    if missing or extra:
        raise ValueError(f"카탈로그 ≠ 등록 op — 카탈로그에 없음 {sorted(missing)} · 등록 안 됨 {sorted(extra)}")
    fams = {f["key"] for f in catalog["families"]}
    out = {}
    for name, spec in specs.items():
        if spec["tier"] not in TIERS or spec["family"] not in fams:
            raise ValueError(f"카탈로그 tier·family 오류: {name}")
        o = Op(name, spec, tools[name])
        if o.direct != (name in {t.name for t in mcp._tool_manager.list_tools()}):
            raise ValueError(f"카탈로그 direct 표식 ≠ 등록: {name}")
        out[name] = o
    return out


# ── 인자 ───────────────────────────────────────────────

def _schema(o):
    """find(op) 의 input_schema — 도구 입력 스키마 그대로(직접 D 도구의 선택 bind 는 겉면 인자라 뺀다)."""
    s = json.loads(json.dumps(o.tool.parameters))
    if o.bind == "hmac":
        s.get("properties", {}).pop("bind", None)
        if "required" in s:
            s["required"] = [r for r in s["required"] if r != "bind"]
    return s


def validate(o, params) -> dict:
    """SDK 와 같은 입력 모델로 검증 → 함수에 넘길 kwargs. 실패 = ARG-INVALID + detail{expected(틀린 필드 스키마), example}."""
    if params is None:
        params = {}
    if not isinstance(params, dict):
        raise crm_error("ARG-INVALID", "params 는 JSON 객체예요.", f"find(op=\"{o.name}\") 로 인자 모양을 보세요.",
                        {"expected": {"type": "object"}, "example": o.examples[0] if o.examples else {}})
    try:
        return o.tool.fn_metadata.validate_arguments(params)
    except ValidationError as e:
        props = _schema(o).get("properties", {})
        fields = []
        for err in e.errors():
            f = str(err["loc"][0]) if err.get("loc") else ""
            if f and f not in fields:
                fields.append(f)
        msg = "; ".join(f"{'.'.join(str(x) for x in err.get('loc', ()))}: {err.get('msg', '')}" for err in e.errors()[:5])
        raise crm_error("ARG-INVALID", f"{o.name} 인자가 맞지 않아요 — {msg}", f"find(op=\"{o.name}\") 로 인자 모양을 보세요.",
                        {"expected": {f: props.get(f, {}) for f in fields}, "example": o.examples[0] if o.examples else {}})


def normalize(op, args) -> dict:
    """bind 계산용 정규화 params — 입력 모델로 다시 읽어 기본값을 채우고 JSON 값으로(직접·facade 같은 결과). bind·ctx 는 뺀다."""
    o = OPS[op]
    raw = {k: v for k, v in args.items() if k not in ("bind", o.tool.context_kwarg)}
    m = o.tool.fn_metadata.arg_model.model_validate(o.tool.fn_metadata.pre_parse_json(raw))
    return m.model_dump(mode="json", exclude={"bind"})


# ── bind ──────────────────────────────────────────────

def _key() -> bytes:
    """bind 키 — CRM_SESSION_SECRET 에서 파생(새 env 없음). 호출 때마다 읽는다(시험이 바꾼다).
    비밀이 없으면 개발(CRM_DEV=1)은 고정 개발 키, 운영은 BIND-UNAVAILABLE."""
    secret = env("SESSION_SECRET", "") or ""
    if not secret:
        if env("DEV") == "1":
            secret = "dev-only-bind-secret"
        else:
            raise crm_error("BIND-UNAVAILABLE", "서버 설정이 빠져 확정·삭제 확인을 만들 수 없어요.", "운영자에게 문의하세요.")
    return hmac.new(secret.encode(), b"bind-v1", hashlib.sha256).digest()


def _canon(v) -> bytes:
    return json.dumps(v, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode()


def bind_of(op, norm, snap) -> str:
    mac = hmac.new(_key(), _canon([op, norm, snap]), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac).decode().rstrip("=")[:BIND_LEN]


def _h(*parts) -> str:
    """본문 해시(스냅샷용) — sha256 앞 16자."""
    return hashlib.sha256(_canon(list(parts))).hexdigest()[:16]


def preview(op, norm, uid) -> dict:
    """{shown, impact, irreversible, bind}. 대상이 없으면 그 op 와 같은 꼴의 CrmError."""
    snap, shown, impact, irreversible = PREVIEWS[op](uid, norm)
    snap = {"uid": uid, **snap}
    return {"op": op, "shown": shown, "impact": impact, "irreversible": irreversible, "bind": bind_of(op, norm, snap)}


def bind_gate(op, args, uid_fn, required):
    """guard 가 쓰기 검사 전에 부른다. bind 가 있으면(직접 도구 선택 인자) 또는 facade 경유(required)면 검사.
    없음 = BIND-REQUIRED, 다름 = BIND-STALE + detail 에 새 preview."""
    given = (args.get("bind") or "").strip()
    if not given:
        if required:
            raise crm_error("BIND-REQUIRED", f"{op} 은 먼저 미리보기가 필요해요.",
                            f"read(op=\"decide_preview\", params={{\"op\": \"{op}\", \"params\": …}}) 의 shown 을 사용자에게 그대로 "
                            "보여 주고, 사용자가 말하면 그 bind 로 다시 부르세요.")
        return
    norm = normalize(op, args)
    pv = preview(op, norm, uid_fn())
    if not hmac.compare_digest(pv["bind"], given):
        raise crm_error("BIND-STALE", "미리보기 뒤 대상이나 인자가 바뀌었어요(또는 bind 가 틀려요).",
                        "새 미리보기(detail)의 shown 을 사용자에게 다시 보여 주고, 사용자가 말하면 새 bind 로 부르세요.", pv)


# ── shown 빌더 (D∪P op 마다 하나 — 시험 K2 가 hmac_ops() 와 대칭을 본다) ──
# 반환 (스냅샷{revision·본문 해시·상태}, shown, impact, irreversible). 읽기만 한다. 시각으로 바뀌는 값은 스냅샷에 넣지 않는다.

def _row(sql, args):
    with db.tx() as c:
        return db._one(c, sql, args)


def _iso(v):
    return v.isoformat() if hasattr(v, "isoformat") else v


_CAND_ACT = {"confirm": "내 판단으로 남기기", "exclude": "남기지 않기", "pending": "아직 안 정함으로 되돌리기", "edit": "문장 고치기"}


def _pv_candidate_decide(uid, p):
    cand = db.candidate_get(uid, p["candidate_id"])
    rec = _row("SELECT title FROM records WHERE user_id=%s AND id=%s", (uid, cand["record_id"]))
    shown = {"후보 문장": cand["text"], "근거 인용": cand["quote"], "근거 기록": rec["title"] if rec else None,
             "지금 상태": cand["status"], "할 일": _CAND_ACT.get(p["action"], p["action"])}
    if p["action"] == "edit":
        shown["고친 문장"] = p.get("text", "")
    if cand.get("review"):
        shown["재검토 사유"] = cand["review"]
    snap = {"status": cand["status"], "body": _h(cand["text"], cand["quote"]), "review": cand.get("review")}
    return snap, shown, {"candidate_id": cand["id"], "record_id": cand["record_id"]}, False


_ITEM_ACT = {"apply": "제안 적용", "confirm": "기준을 내 판단으로 남기기", "exclude": "남기지 않기", "pending": "아직 안 정함으로",
             "archive": "보관", "restore": "이력 시점으로 되돌리기", "discard": "제안 버리기"}


def _pv_item_decide(uid, p):
    r = _row("SELECT i.id,i.code,i.title,i.body,i.decision,i.revision,i.archived_at,i.draft_id,i.draft_doc,o.label AS object_label "
             "FROM items i JOIN object_defs o ON o.user_id=i.user_id AND o.id=i.object_id "
             "WHERE i.user_id=%s AND i.id=%s AND i.trashed_at IS NULL", (uid, p["item_id"]))
    if not r:
        raise db.CrmError("ARG-INVALID", f"항목을 찾을 수 없어요: {p['item_id']}")
    shown = {"종류": r["object_label"], "코드": r["code"], "제목": r["title"], "본문": r["body"], "지금 상태": r["decision"],
             "할 일": _ITEM_ACT.get(p["action"], p["action"])}
    d = r["draft_doc"] if isinstance(r["draft_doc"], dict) else None
    if p["action"] in ("apply", "discard") and d:
        shown["제안"] = {k: d.get(k) for k in ("title", "body", "code") if k in d}
    if p["action"] == "restore":
        shown["되돌릴 이력"] = p.get("history_id")
    snap = {"revision": r["revision"], "decision": r["decision"], "archived": r["archived_at"] is not None,
            "body": _h(r["code"], r["title"], r["body"], r["draft_id"], r["draft_doc"])}
    return snap, shown, {"item_id": r["id"], "revision": r["revision"]}, False


def _def_row(uid, oid):
    r = _row("SELECT id,label,revision,archived_at,std_id,draft_id,draft_doc FROM object_defs WHERE user_id=%s AND id=%s", (uid, str(oid or "")))
    if not r:
        raise db.CrmError("ARG-INVALID", f"오브젝트를 찾을 수 없어요: {oid}", "definitions_get 으로 ID 를 확인하세요.")
    return r


def _pv_definition_apply(uid, p):
    r = _def_row(uid, p["object_id"])
    d = r["draft_doc"] if isinstance(r["draft_doc"], dict) else {}
    fields = [f"{f.get('key')}: {f.get('label')} ({f.get('value_type')})" for f in d.get("fields", []) if isinstance(f, dict)]
    shown = {"자료 종류": r["label"], "지금 revision": r["revision"], "제안 이름": d.get("label"), "제안 필드": fields}
    snap = {"revision": r["revision"], "draft_id": r["draft_id"], "body": _h(r["draft_doc"])}
    return snap, shown, {"object_id": r["id"], "fields": len(fields)}, False


def _def_impact(uid, oid):
    with db.tx() as c:
        items = db._one(c, "SELECT count(*) AS n FROM items WHERE user_id=%s AND object_id=%s AND archived_at IS NULL AND trashed_at IS NULL",
                        (uid, oid))["n"]
        refs = db._one(c, "SELECT count(*) AS n FROM field_defs WHERE user_id=%s AND target_object_id=%s AND object_id <> %s "
                          "AND archived_at IS NULL", (uid, oid, oid))["n"]
    return {"items": items, "referencing_fields": refs}


def _pv_def_archive(archive):
    def build(uid, p):
        r = _def_row(uid, p["object_id"])
        impact = _def_impact(uid, r["id"])
        shown = {"자료 종류": r["label"], "할 일": "보관(목록에서 빠짐, 항목은 지우지 않음)" if archive else "보관 풀기",
                 "항목 수": impact["items"], "이 종류를 가리키는 다른 필드 수": impact["referencing_fields"]}
        snap = {"revision": r["revision"], "archived": r["archived_at"] is not None, "std": r["std_id"], **impact}
        return snap, shown, impact, False
    return build


def _pv_record_provenance_set(uid, p):
    r = _row("SELECT id,title,body,author_kind,text_process FROM records WHERE user_id=%s AND id=%s AND deleted_at IS NULL "
             "AND trashed_at IS NULL", (uid, p["record_id"]))
    if not r:
        raise db.CrmError("RECORD-MISSING", f"기록을 찾을 수 없어요: {p['record_id']}")
    shown = {"기록": r["title"], "작성자 전": r["author_kind"], "작성자 후": p["author_kind"],
             "가공 방식 전": r["text_process"], "가공 방식 후": p["text_process"], "사유": p["reason"]}
    snap = {"author_kind": r["author_kind"], "text_process": r["text_process"], "body": _h(r["title"], r["body"])}
    return snap, shown, {"record_id": r["id"]}, False


def _refl_row(uid, rid):
    r = _row("SELECT id,source_id,kind,body,review,revision FROM source_reflections WHERE user_id=%s AND id=%s AND trashed_at IS NULL",
             (uid, str(rid or "")))
    if not r:
        raise db._nf("그 요약/반응")
    return r


def _pv_source_reflection_review(uid, p):
    r = _refl_row(uid, p["reflection_id"])
    shown = {"유형": r["kind"], "본문": r["body"], "지금 검토": r["review"], "바꿀 검토": "reviewed" if p["reviewed"] else "pending",
             "참고": "검토 완료는 판단 확정이 아니고 근거로 인용할 수 없다"}
    snap = {"revision": r["revision"], "review": r["review"], "body": _h(r["kind"], r["body"])}
    return snap, shown, {"reflection_id": r["id"], "revision": r["revision"]}, False


def _delete_shown(on):
    return f"휴지통으로 이동({db.TRASH_HOURS}시간 안에 복원 가능)" if on else "바로 지워짐 — 되돌릴 수 없음"


def _pv_person_delete(uid, p):
    r = _row("SELECT id,alias,revision FROM people WHERE user_id=%s AND id=%s AND trashed_at IS NULL", (uid, str(p["person_id"] or "")))
    if not r:
        raise db._nf("그 사람")
    on = db.trash_on()
    shown = {"사람": r["alias"], "결과": _delete_shown(on)}
    return {"revision": r["revision"], "body": _h(r["alias"]), "trash_on": on}, shown, {"person_id": r["id"]}, not on


def _pv_source_reflection_delete(uid, p):
    r = _refl_row(uid, p["reflection_id"])
    on = db.trash_on()
    shown = {"유형": r["kind"], "본문": r["body"], "결과": _delete_shown(on)}
    return {"revision": r["revision"], "body": _h(r["kind"], r["body"]), "trash_on": on}, shown, {"reflection_id": r["id"]}, not on


_TRASH_KIND_LABEL = {"record": "내 글", "item": "항목", "person": "사람", "reflection": "읽고 든 생각", "activity": "활동"}


def _trash_target(uid, kind, tid):
    t = db.TRASH_KINDS.get(kind)
    if t is None:
        raise db.CrmError("ARG-INVALID", f"kind 는 {', '.join(db.TRASH_KINDS)} 중 하나예요.")
    a = {"now": None, "uid": uid, "id": str(tid or "")}
    with db.tx() as c:
        st = db._one(c, f"SELECT trashed_at,purge_at FROM {t} WHERE user_id=%(uid)s AND id=%(id)s", a)
        row = db._one(c, db._TRASH_GET_SQL[kind], a) if st else None
    if not st or not row:
        raise db._nf(db._TRASH_NAMES[kind])
    if kind == "record":
        title = row["title"]
    elif kind == "item":
        title = f"{row['object_label']} · {row['title']}"
    elif kind == "person":
        title = row["alias"]
    elif kind == "reflection":
        title = (row["body"] or "").strip().splitlines()[0][:60] if (row["body"] or "").strip() else ""
    else:
        import activity
        title = activity.ACTION_LABELS.get(row["action"], row["action"])
    snap = {"trashed_at": _iso(st["trashed_at"]), "purge_at": _iso(st["purge_at"]), "revision": row.get("revision"),
            "body": _h({k: _iso(v) for k, v in row.items()})}
    return st, title, snap


def _pv_trash(op):
    def build(uid, p):
        st, title, snap = _trash_target(uid, p["kind"], p["target_id"])
        shown = {"종류": _TRASH_KIND_LABEL[p["kind"]], "제목": title}
        if op == "move":
            shown["결과"] = f"휴지통으로 이동 — {db.TRASH_HOURS}시간 안에 복원할 수 있어요"
        elif op == "restore":
            shown["결과"] = "삭제 직전 상태로 복원(승인·확정 아님)"
            shown["복원 기한"] = _iso(st["purge_at"])
        else:
            shown["결과"] = "영구 삭제 요청 — 지금부터 복원할 수 없어요"
            shown["복원 기한"] = _iso(st["purge_at"])
        return snap, shown, {"kind": p["kind"], "target_id": p["target_id"]}, op == "purge"
    return build


def _pv_feedback_send(uid, p):
    shown = {"종류": p["kind"], "보낼 글": p["text"], "문제 난 도구": p.get("tool") or None}
    return {}, shown, {"to": "운영자"}, True


PREVIEWS = {
    "candidate_decide": _pv_candidate_decide,
    "item_decide": _pv_item_decide,
    "definition_apply": _pv_definition_apply,
    "definition_archive": _pv_def_archive(True),
    "definition_restore": _pv_def_archive(False),
    "record_provenance_set": _pv_record_provenance_set,
    "source_reflection_review": _pv_source_reflection_review,
    "person_delete": _pv_person_delete,
    "source_reflection_delete": _pv_source_reflection_delete,
    "trash_move": _pv_trash("move"),
    "trash_restore": _pv_trash("restore"),
    "trash_purge": _pv_trash("purge"),
    "feedback_send": _pv_feedback_send,
}


# ── 규칙·find ─────────────────────────────────────────

def gate_sentences(doc) -> list[str]:
    """docstring 에서 「…때만 부른다」 류 문장만."""
    sents = re.split(r"(?<=[.。])\s+|\n+", doc or "")
    return [s.strip() for s in sents if s.strip() and _GATE.search(s) and "부르" in s]


def rule_of(o) -> str:
    gates = " ".join(x for x in (" ".join(gate_sentences(o.doc)), RULES.get(o.name, "")) if x)
    if o.bind == "self":
        return f"{SELF_RULE} {gates}".strip()
    if o.tier == "decide":
        return f"{COMMON_RULE} {gates}".strip()
    if o.tier == "purge":
        return f"{COMMON_RULE} {PURGE_RULE} {gates}".strip()
    if o.tier == "write":
        return gates or "사용자가 말한 그대로 저장한다. 다듬거나 추정으로 채우지 않는다."
    return gates or "읽기 전용."


def flow_of(o):
    if o.bind == "hmac":
        return [f"read(op=\"decide_preview\", params={{\"op\": \"{o.name}\", \"params\": {{…}}}}) → shown·bind",
                "shown 을 고치지 않고 사용자에게 그대로 보여 준다", "사용자가 말한 뒤에만",
                f"{o.tier}(op=\"{o.name}\", params={{…같은 params}}, bind=\"…\")"]
    if o.bind == "self":
        pre = ["read(op=\"migration_apply_preview\") → 미리보기를 고치지 않고 그대로 보여 준다"] if o.name == "migration_apply" else []
        return pre + ["사용자가 말한 뒤에만", f"decide(op=\"{o.name}\", params={{…}}) — bind 없음"]
    return None


def _match(o, toks):
    hay_kw = [k.lower() for k in o.keywords]
    name, summ = o.name.lower(), o.summary.lower()
    score = 0
    for t in toks:
        if t in name:
            score += 3
        if any(t in k or k in t for k in hay_kw):
            score += 2
        if t in summ:
            score += 1
    return score


def _entry(o):
    return {"op": o.name, "family": o.family, "tier": o.tier, "summary": o.summary, "user_words": o.keywords, "rule": rule_of(o)}


def find(query="", family="", op="") -> dict:
    """op > query > family 순으로 하나를 본다. 아무것도 없으면 family 목록."""
    labels = {f["key"]: f["label"] for f in FAMILIES}
    if op:
        o = OPS.get(op)
        if o is None:
            raise unknown(op)
        out = {"op": o.name, "tier": o.tier, "family": o.family, "description": o.doc, "input_schema": _schema(o),
               "examples": o.examples, "rule": rule_of(o)}
        if (fl := flow_of(o)) is not None:
            out["flow"] = fl
        return out
    if family and family not in labels:
        raise crm_error("ARG-INVALID", f"family 는 {', '.join(labels)} 중 하나예요.", "find() 로 목록을 보세요.")
    pool = [o for o in OPS.values() if not family or o.family == family]
    if query:
        toks = [t for t in re.split(r"[\s,·/]+", query.lower()) if t]
        scored = sorted(((_match(o, toks), o.name, o) for o in pool), key=lambda x: (-x[0], x[1]))
        return {"matches": [_entry(o) for s, _, o in scored if s > 0][:FIND_MAX]}
    if family:
        return {"family": family, "label": labels[family], "ops": [_entry(o) for o in pool]}
    return {"families": [{"key": f["key"], "label": f["label"],
                          "ops_by_tier": {t: [o.name for o in OPS.values() if o.family == f["key"] and o.tier == t] for t in TIERS}}
                         for f in FAMILIES]}


def unknown(op):
    near = difflib.get_close_matches(str(op), list(OPS), n=3, cutoff=0.0)
    return crm_error("OP-UNKNOWN", f"모르는 op 이에요: {op}", "find(query=…) 로 찾으세요.", {"near": near})


# ── 겉면 디스패치 ──────────────────────────────────────

def _count(ctx, name, code):
    """facade 단계 거절(안쪽 guard 에 닿기 전)만 센다 — 1호출 = 1집계."""
    uid = None
    try:
        uid = uid_of(ctx)
    except Exception:
        pass
    db.usage_count(uid, name, code)


def dispatch(surface, op, params, ctx, bind=None):
    """등급 검사(TIER-MISMATCH) → 입력 검증(ARG-INVALID) → guard 함수 호출(같은 스레드, VIA=f). bind 검사는 안쪽 guard 가 한다."""
    o = OPS.get(op)
    try:
        if o is None:
            raise unknown(op)
        if o.tier != surface:
            raise crm_error("TIER-MISMATCH", f"{op} 은 {o.tier} 등급이에요 — {surface} 로 부를 수 없어요.", f"{o.tier}(op=\"{op}\", …) 로 부르세요.",
                            {"tier": o.tier})
        if isinstance(params, dict) and "bind" in params and o.bind == "hmac":
            raise crm_error("ARG-INVALID", "bind 는 params 밖(겉면 인자)으로 보내요.", f"{surface}(op, params, bind) 로 부르세요.")
        kw = validate(o, params)
    except db.CrmError as e:
        _count(ctx, f"f:{op}" if o is not None else "f:?", e.code)
        raise ToolError(error_text(e.code, e.message, e.action, getattr(e, "detail", None)))
    if o.bind == "hmac":
        kw["bind"] = bind or ""
    if o.tool.context_kwarg:
        kw[o.tool.context_kwarg] = ctx
    token = VIA.set("f")
    try:
        result = o.tool.fn(**kw)
    finally:
        VIA.reset(token)
    out = o.tool.fn_metadata.convert_result(result)
    if surface in ("decide", "purge") and isinstance(result, dict):
        res = {**result, "via": "facade"}
        out = CallToolResult(content=[TextContent(type="text", text=pydantic_core.to_json(res, fallback=str, indent=2).decode())],
                             structured_content=res)
    return out


def decide_preview_fn(ops):
    """read(op="decide_preview") — D∪P(자기 바인딩 제외) op 의 shown·impact·irreversible·bind. 쓰지 않는다."""
    enum = {"enum": list(ops)}

    def decide_preview(
        op: Annotated[str, Field(description="미리 볼 확정·삭제 op (decide·purge 등급, 이관 제외)", json_schema_extra=enum)],
        params: Annotated[dict[str, Any], Field(description="그 op 에 그대로 보낼 params")],
        ctx: Context,
    ) -> dict:
        """확정·삭제 전 미리보기 — 사용자에게 보여 줄 shown(고치지 않고 그대로)·영향·되돌릴 수 없는지·bind. 아무것도 바꾸지 않는다.
        사용자가 shown 을 보고 말한 뒤에만 그 bind 로 decide·purge 를 부른다. 이관 반영은 migration_apply_preview 를 쓴다."""
        o = OPS.get(op)
        if o is None:
            raise unknown(op)
        if o.bind != "hmac":
            raise crm_error("TIER-MISMATCH", f"{op} 은 decide_preview 대상이 아니에요.",
                            "이관은 read(op=\"migration_apply_preview\") 를 쓰세요." if o.bind == "self" else "확정·삭제 op 만 미리 봐요.",
                            {"tier": o.tier, "bind": o.bind})
        if "bind" in params:
            raise crm_error("ARG-INVALID", "bind 는 params 에 넣지 않아요.", "")
        validate(o, params)
        return preview(op, normalize(op, params), uid_of(ctx))
    return decide_preview


# ── 겉면 5개 등록 ─────────────────────────────────────

def _desc_decide(tier):
    lines = [f"{'확정·변경·휴지통 이동/복원·보관·밖으로 보내기' if tier == 'decide' else '영구 삭제'} op 을 부른다. "
             f"op 목록은 enum, 인자는 find(op=…) 로 본다. 먼저 read(op=\"decide_preview\", params={{op, params}}) 로 bind 를 받는다.",
             f"공통: {COMMON_RULE}"]
    if tier == "purge":
        lines.append(PURGE_RULE)
    for n in ops_of(tier):
        o = OPS[n]
        g = " ".join(gate_sentences(o.doc)) or o.summary
        lines.append(f"- {n}: " + " ".join(x for x in ((SELF_RULE if o.bind == "self" else ""), g) if x))
    return "\n".join(lines)


def install(mcp, guard, uid_fn, extra_ops=(), rules=None):
    """카탈로그 로드 → 등록부 → 겉면 5개 등록. main.py 가 직접 도구를 다 등록한 뒤 한 번 부른다.
    extra_ops = facade 전용 op 함수(직접 도구처럼 ctx 를 받는 서명) · rules = op 별 덧붙일 규칙 문장."""
    global _uid_of, OPS, FAMILIES, RULES
    _uid_of = uid_fn
    RULES = dict(rules or {})
    catalog = load_catalog()
    FAMILIES = list(catalog["families"])
    D_P = [n for n, s in catalog["ops"].items() if s["tier"] in ("decide", "purge") and s.get("bind") != "self"]
    preview_fn = decide_preview_fn(D_P)
    OPS = build_registry(mcp, guard, catalog, (preview_fn, *extra_ops))
    if set(PREVIEWS) != set(hmac_ops()):
        raise ValueError(f"shown 빌더 ≠ 확정·삭제 op — {sorted(set(PREVIEWS) ^ set(hmac_ops()))}")

    def op_field(tier):
        return Field(description=f"{tier} 등급 op 이름(지금 도구 이름 그대로)", json_schema_extra={"enum": ops_of(tier)})

    P = Annotated[dict[str, Any] | None, Field(description="op 인자 객체 — 모양은 find(op=…) 의 input_schema·examples")]
    B = Annotated[str, Field(description="read(op=\"decide_preview\") 가 준 bind. 없거나 낡으면 거절된다")]
    fam_keys = [f["key"] for f in FAMILIES]

    def find_tool(
        ctx: Context,
        query: Annotated[str, Field(description="찾을 말(사용자 표현 그대로도 된다). 부분 일치")] = "",
        family: Annotated[str, Field(description="이 묶음만 (선택)", json_schema_extra={"enum": ["", *fam_keys]})] = "",
        op: Annotated[str, Field(description="이 op 의 설명·입력 스키마·예시·규칙 (선택)")] = "",
    ) -> dict:
        return find(query, family, op)
    find_tool.__name__ = "find"
    find_tool.__doc__ = ("이 서버의 할 일(op)을 찾는다. 인자 없음 = 묶음 목록, query = 말로 찾기(최대 8), op = 그 op 의 설명·input_schema·examples·rule. "
                         "찾은 op 은 등급 도구(read·write·decide·purge)로 부른다. 확정·삭제는 decide_preview → decide/purge.")

    def read(op: Annotated[str, op_field("read")], ctx: Context, params: P = None) -> CallToolResult:
        return dispatch("read", op, params, ctx)
    read.__doc__ = ("읽기 op 을 부른다(아무것도 바꾸지 않는다). op 목록은 enum, 인자는 find(op=…). "
                    "확정·삭제 전 미리보기는 op=\"decide_preview\", params={op, params}.")

    def write(op: Annotated[str, op_field("write")], ctx: Context, params: P = None) -> CallToolResult:
        return dispatch("write", op, params, ctx)
    write.__doc__ = ("사용자 말을 그대로 저장하거나 제안(draft)만 남기는 op 을 부른다. 다듬거나 추정으로 채우지 않는다. "
                     "op 목록은 enum, 인자는 find(op=…).")

    def decide(op: Annotated[str, op_field("decide")], ctx: Context, params: P = None, bind: B = "") -> CallToolResult:
        return dispatch("decide", op, params, ctx, bind)
    decide.__doc__ = _desc_decide("decide")

    def purge(op: Annotated[str, op_field("purge")], ctx: Context, params: P = None, bind: B = "") -> CallToolResult:
        return dispatch("purge", op, params, ctx, bind)
    purge.__doc__ = _desc_decide("purge")

    ro = ToolAnnotations(read_only_hint=True)
    mcp.add_tool(guard(find_tool), name="find", annotations=ro)
    mcp.add_tool(read, annotations=ro, structured_output=False)
    mcp.add_tool(write, structured_output=False)
    mcp.add_tool(decide, structured_output=False)
    mcp.add_tool(purge, annotations=ToolAnnotations(destructive_hint=True), structured_output=False)
    return OPS
