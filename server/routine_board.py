"""첫 화면 루틴판(2026-11-21 구현계획 2-2, 2-3) — 읽기만. 웹 GET /api/me/routine[/<item_id>] 와 MCP routine_board_get,
routine_board_detail_get 이 같은 함수를 쓴다.

설정 p = 저장된 「나」 배치의 routine 블록 p(db._routine_p_check 를 지난 값). 키 in, decided, writing, lines, subheads = 오브젝트 key,
in_signal, stage = "칸key:값", verdict = 칸 key. 오브젝트 칸 key 는 정의(구현계획 1절)를 따른다 — 아래 상수.

정한 읽기(명세가 따로 정하지 않은 곳):
- 오브젝트 = 적용(revision > 0), 미보관. 아니면 missing 에 그 p 키(in, decided 등)를 넣는다. missing 이 있으면 ready = false, 숫자 0, 목록 빈 값.
- 항목 = 적용, 미보관, 휴지통 아님. 기록 = 지우지 않음, 휴지통 아님.
- 항목의 날짜 = 정의 순서상 첫 date 칸 값(YYYY-MM-DD 로 읽히는 것만), 없으면 created_at 의 KST 날짜. 기록의 날짜 = source_date,
  source_created_at, created 순(KST).
- verdict 가 없으면 decided 의 모든 항목이 none 이다.
- decided 열 대상 = route 원문 기록(item_routes.record_id, item_id 있는 행)이 있는 decided 항목. route 가 없는 항목은 첫 화면 줄을 달 수
  없어 unrefined 에 세지 않는다. 기록 하나에 항목이 여럿(### 분할)이면 줄의 target.item_id 는 가장 먼저 만든 항목이다.
- 같은 대상에 첫 화면 줄이 여럿이면 가장 최근에 바뀐 줄 하나만 쓴다.
- last_routine_at = front_lines, subheads, writing 항목의 적용 이력(item_history action apply) 중 가장 늦은 시각.
- 카드 n_sources = 소제목들의 출처 합(중복 제외). n_posts, n_records = 소제목 출처에 한판 유입 글(inflow_posts), 재료(materials)를 더한
  수집 글 수, 기록 수(중복 제외, 2026-11-21 명세 수정).
- 상세 sources 는 수집 글 ref 가 먼저, 기록 ref 가 뒤다. inflow, decided 는 소제목 순서대로 모은 뒤 한판 칸 값을 붙인다(중복 제외).
  missing_sources = 상세의 모든 참조 중 지금 보이지 않는 대상(휴지통, 보관, 지움) 수(중복 제외).
- AI 값(ai_*)은 판 응답에 넣지 않는다. 상세의 수집 글 ref 만 ai_summary 를 ai: true 와 함께 싣는다 — 근거가 아니다.
"""
import datetime as _dt
import unicodedata

import db
from db import CrmError, _all, _one, tx

# 정의(구현계획 1절)의 칸 key
F_BOARD, F_ORDER, F_SRC_RECORDS, F_SRC_POSTS = "board", "order", "src_records", "src_posts"   # 소제목
F_SUBJECT_RECORD, F_SUBJECT_POST = "subject_record", "subject_post"                           # 첫 화면 줄
F_KEY_LINE, F_INFLOW, F_MATERIALS, F_STAGE = "key_line", "inflow_posts", "materials", "stage"   # 한판
F_AUTHOR, F_CHANNEL, F_AI_SUMMARY = "author_display", "channel", "ai_summary"                  # 수집 글

LINES_MAX = 3
CARDS_MAX = 3
WEEK_DAYS = 7

# 첫 낱말 규칙(3-A). 위에서부터 보고 처음 맞는 것
VERDICT_WORDS = (("right", ("맞았다", "맞음", "맞다")), ("unknown", ("미확인",)), ("partial", ("일부",)),
                 ("wrong", ("틀렸다", "틀림", "아니었다")))
VERDICTS = ("right", "unknown", "partial", "wrong", "none")

_LIVE_I = "i.revision > 0 AND i.archived_at IS NULL AND i.trashed_at IS NULL"   # 별칭 i 항목이 살아 있다
_LIVE = "i.user_id=%s AND " + _LIVE_I
_KST_DAY = "(({}) AT TIME ZONE 'Asia/Seoul')::date"
_REC_DAY = f"COALESCE(r.source_date, {_KST_DAY.format('r.source_created_at')}, {_KST_DAY.format('r.created')})"


def verdict_of(v):
    """판정 칸 값 → right|unknown|partial|wrong|none. 앞 공백과 문장부호를 뺀 첫 어절이 표의 낱말로 시작하는지 본다."""
    if not isinstance(v, str):
        return "none"
    s = v
    while s and (s[0].isspace() or unicodedata.category(s[0])[0] in "PS"):
        s = s[1:]
    word = s.split(None, 1)[0] if s.split() else ""
    for name, words in VERDICT_WORDS:
        if any(word.startswith(w) for w in words):
            return name
    return "none"


def _empty(ready=False, missing=()):
    col = {"lines": [], "more": 0, "unrefined": 0}
    return {"ready": ready, "missing": list(missing), "last_routine_at": None, "since": {"new_in": 0, "new_decided": 0},
            "in": {"n_total": 0, "n_7d": 0, "signal_7d": 0, **col},
            "decided": {"total": 0, **{k: 0 for k in VERDICTS}, **col},
            "writing": {"drafts": 0, "cards": []}}


def _pair(v):
    if not v:
        return None, None
    f, _, val = v.partition(":")
    return f.strip(), val.strip()


def routine_p(uid):
    """저장된 「나」 배치에서 routine 블록 p — 없으면 None. 모양이 틀린 저장값은 db._layout_up 이 기본 배치로 돌린다(그러면 None)."""
    with tx() as c:
        r = _one(c, "SELECT layout FROM page_layouts WHERE user_id=%s", (uid,))
    lay = db._layout_up(r["layout"] if r else None)
    for page in lay["pages"].values():
        for entries in page["regions"].values():
            for e in entries:
                if e["c"] == db.ROUTINE_BLOCK:
                    return dict(e["p"])
    return None


def _objects(c, uid, p):
    """p 의 오브젝트 키 → {p 키: {id, key, date_field}}, missing(p 키 목록)."""
    keys = {k: p[k] for k in db.ROUTINE_OBJ_KEYS}
    rows = {r["key"]: r for r in _all(c, "SELECT id, key FROM object_defs WHERE user_id=%s AND key = ANY(%s) AND revision > 0 "
                                         "AND archived_at IS NULL", (uid, list(set(keys.values()))))}
    dfs = _date_fields(c, uid, [r["id"] for r in rows.values()])
    objs, missing = {}, []
    for k, key in keys.items():
        r = rows.get(key)
        if r:
            objs[k] = {"id": r["id"], "key": key, "date_field": dfs.get(r["id"])}
        else:
            missing.append(k)
    return objs, missing


def _date_fields(c, uid, oids):
    out = {}
    if oids:
        for r in _all(c, "SELECT object_id, key FROM field_defs WHERE user_id=%s AND object_id = ANY(%s) AND value_type='date' "
                         "AND archived_at IS NULL ORDER BY object_id, position, key", (uid, list(oids))):
            out.setdefault(r["object_id"], r["key"])
    return out


def _day(row, date_field):
    v = (row["data"] or {}).get(date_field) if date_field else None
    if isinstance(v, str) and len(v) == 10:
        try:
            return _dt.date.fromisoformat(v)
        except ValueError:
            pass
    return row["cday"]


def _items(c, uid, oid, ids=None):
    sql = (f"SELECT i.id, i.object_id, i.title, i.body, i.data, i.created_at, i.updated_at, {_KST_DAY.format('i.created_at')} AS cday "
           f"FROM items i WHERE {_LIVE} AND i.object_id=%s")
    args = [uid, oid]
    if ids is not None:
        sql += " AND i.id = ANY(%s)"
        args.append(list(ids))
    return _all(c, sql, args)


def _links(c, uid, src_ids, fields):
    """출발 항목들의 관계 → 행 목록(링크 id 순)."""
    if not src_ids:
        return []
    return _all(c, "SELECT source_item_id AS src, field_key AS f, target_item_id AS ti, target_record_id AS tr FROM item_links "
                   "WHERE user_id=%s AND source_item_id = ANY(%s) AND field_key = ANY(%s) ORDER BY id",
                (uid, list(src_ids), list(fields)))


def _live_items(c, uid, ids):
    if not ids:
        return {}
    return {r["id"]: r for r in _all(c, f"SELECT i.id, i.object_id, i.title, i.data, {_KST_DAY.format('i.created_at')} AS cday "
                                        f"FROM items i WHERE {_LIVE} AND i.id = ANY(%s)", (uid, list(ids)))}


def _live_records(c, uid, ids):
    if not ids:
        return {}
    return {r["id"]: r for r in _all(c, f"SELECT r.id, r.title, {_REC_DAY} AS d FROM records r WHERE r.user_id=%s "
                                        "AND r.id = ANY(%s) AND r.deleted_at IS NULL AND r.trashed_at IS NULL", (uid, list(ids)))}


def _route_items(c, uid, oid, record_ids=None):
    """decided 오브젝트의 route 항목 → {record_id: [item 행(만든 순)]}. 항목, 기록 모두 살아 있는 것만."""
    sql = ("SELECT ir.record_id, i.id, i.title, i.data, i.created_at FROM item_routes ir JOIN items i ON i.user_id=ir.user_id "
           "AND i.id=ir.item_id JOIN records r ON r.user_id=ir.user_id AND r.id=ir.record_id "
           f"WHERE ir.user_id=%s AND ir.object_id=%s AND ir.item_id IS NOT NULL AND {_LIVE_I} "
           "AND r.deleted_at IS NULL AND r.trashed_at IS NULL")
    args = [uid, oid]
    if record_ids is not None:
        sql += " AND ir.record_id = ANY(%s)"
        args.append(list(record_ids))
    out = {}
    for r in _all(c, sql + " ORDER BY i.created_at, i.id", args):
        out.setdefault(r["record_id"], []).append(r)
    return out


def _today(c):
    return _one(c, "SELECT (now() AT TIME ZONE 'Asia/Seoul')::date AS d")["d"]


def routine_board(uid, p=None):
    """루틴판 집계(구현계획 2-2). p 없음 = 저장된 배치의 routine 블록 p. 반환 모양은 ui/src/features/me/routine.sample.json 의 board."""
    if p is None:
        p = routine_p(uid)
    if not p:
        return _empty()
    with tx() as c:
        objs, missing = _objects(c, uid, p)
        if missing:
            return _empty(missing=missing)
        today = _today(c)
        week0 = today - _dt.timedelta(days=WEEK_DAYS - 1)
        o_in, o_dec, o_wr, o_ln, o_sh = (objs[k] for k in db.ROUTINE_OBJ_KEYS)

        # 들어온 것
        ins = _items(c, uid, o_in["id"])
        in_day = {r["id"]: _day(r, o_in["date_field"]) for r in ins}
        sf, sv = _pair(p.get("in_signal"))
        n_7d = sum(1 for d in in_day.values() if week0 <= d <= today)
        sig = sum(1 for r in ins if sf and week0 <= in_day[r["id"]] <= today and str((r["data"] or {}).get(sf)) == sv)

        # 내가 정한 것
        decs = _items(c, uid, o_dec["id"])
        dec_ids = {r["id"] for r in decs}
        vf = p.get("verdict")
        counts = {k: 0 for k in VERDICTS}
        for r in decs:
            counts[verdict_of((r["data"] or {}).get(vf)) if vf else "none"] += 1
        routes = _route_items(c, uid, o_dec["id"])
        dec_day = {r["id"]: _day(r, o_dec["date_field"]) for r in decs}

        # 첫 화면 줄 → 열
        fls = _items(c, uid, o_ln["id"])
        fl_by = {r["id"]: r for r in fls}
        best = {}   # (kind, target id) → 첫 화면 줄 행(가장 최근에 바뀐 것)
        for ln in _links(c, uid, list(fl_by), (F_SUBJECT_RECORD, F_SUBJECT_POST)):
            key = ("item", ln["ti"]) if ln["f"] == F_SUBJECT_POST and ln["ti"] else ("record", ln["tr"]) if ln["tr"] else None
            if not key:
                continue
            fl = fl_by[ln["src"]]
            cur = best.get(key)
            if cur is None or (fl["updated_at"], fl["id"]) > (cur["updated_at"], cur["id"]):
                best[key] = fl
        in_lines, dec_lines = [], []
        for (kind, tid), fl in best.items():
            if kind == "item" and tid in in_day:
                in_lines.append((in_day[tid], fl, {"kind": "item", "id": tid, "object_key": o_in["key"], "item_id": tid}))
            elif kind == "record" and tid in routes:
                it = routes[tid][0]
                dec_lines.append((dec_day[it["id"]], fl, {"kind": "record", "id": tid, "object_key": o_dec["key"], "item_id": it["id"]}))
        in_unref = sum(1 for i in in_day if ("item", i) not in best)
        dec_unref = sum(1 for rid, its in routes.items() if ("record", rid) not in best for it in its if it["id"] in dec_ids)

        # 쓰는 중
        stf, stv = _pair(p.get("stage"))
        wrs = [r for r in _items(c, uid, o_wr["id"]) if not stf or str((r["data"] or {}).get(stf)) == stv]
        wr_day = {r["id"]: _day(r, o_wr["date_field"]) for r in wrs}
        wrs.sort(key=lambda r: (wr_day[r["id"]], r["created_at"], r["id"]), reverse=True)
        top = wrs[:CARDS_MAX]
        sh_of, src_of, all_of = _subheads_sources(c, uid, o_sh["id"], [r["id"] for r in top])
        n_kind = lambda bid, kind: sum(1 for k in all_of.get(bid, ()) if k[0] == kind)   # noqa: E731
        cards = [{"item_id": r["id"], "key_line": _key_line(r), "date": wr_day[r["id"]].isoformat(),
                  "n_subheads": len(sh_of.get(r["id"], ())), "n_sources": len(src_of.get(r["id"], ())),
                  "n_posts": n_kind(r["id"], "post"), "n_records": n_kind(r["id"], "record")} for r in top]

        # 지난 루틴 뒤
        last = _one(c, "SELECT max(h.at) AS t FROM item_history h JOIN items i ON i.user_id=h.user_id AND i.id=h.item_id "
                       f"WHERE h.user_id=%s AND h.action='apply' AND {_LIVE_I} AND i.object_id = ANY(%s)",
                    (uid, [o_ln["id"], o_sh["id"], o_wr["id"]]))["t"]
        new_in = sum(1 for r in ins if last is None or r["created_at"] > last)
        new_dec = sum(1 for r in decs if last is None or r["created_at"] > last)

    def col(rows):
        rows.sort(key=lambda x: (x[0], x[1]["updated_at"], x[1]["id"]), reverse=True)
        return [{"date": d.isoformat(), "text": fl["title"], "target": t} for d, fl, t in rows[:LINES_MAX]], max(0, len(rows) - LINES_MAX)

    il, im = col(in_lines)
    dl, dm = col(dec_lines)
    return {"ready": True, "missing": [], "last_routine_at": last.isoformat() if last else None,
            "since": {"new_in": new_in, "new_decided": new_dec},
            "in": {"n_total": len(ins), "n_7d": n_7d, "signal_7d": sig, "lines": il, "more": im, "unrefined": in_unref},
            "decided": {"total": len(decs), **counts, "lines": dl, "more": dm, "unrefined": dec_unref},
            "writing": {"drafts": len(wrs), "cards": cards}}


def _key_line(r):
    v = (r["data"] or {}).get(F_KEY_LINE)
    return v if isinstance(v, str) and v.strip() else r["title"]


def _subheads_sources(c, uid, sh_oid, board_ids):
    """한판들 → ({한판 id: [소제목 id]}, {한판 id: {(kind, id)}} 소제목 출처, {한판 id: {(kind, id)}} 소제목 출처 + 한판 유입 글, 재료).
    출처는 살아 있는 대상만 센다."""
    if not board_ids:
        return {}, {}, {}
    board_of = {r["src"]: r["b"] for r in _all(c, "SELECT l.source_item_id AS src, l.target_item_id AS b FROM item_links l JOIN items i "
                                              "ON i.user_id=l.user_id AND i.id=l.source_item_id WHERE l.user_id=%s AND l.field_key=%s "
                                              f"AND l.target_item_id = ANY(%s) AND i.object_id=%s AND {_LIVE_I}",
                                           (uid, F_BOARD, list(board_ids), sh_oid))}
    sh_ids = list(board_of)
    srcs = _links(c, uid, sh_ids, (F_SRC_RECORDS, F_SRC_POSTS))
    own = _links(c, uid, list(board_ids), (F_INFLOW, F_MATERIALS))
    items = _live_items(c, uid, {s["ti"] for s in srcs + own if s["ti"]})
    recs = _live_records(c, uid, {s["tr"] for s in srcs + own if s["tr"]})
    sh_of, src_of, all_of = {}, {}, {}
    for s in sh_ids:
        sh_of.setdefault(board_of[s], []).append(s)
    key = lambda s: ("post", s["ti"]) if s["ti"] in items else ("record", s["tr"]) if s["tr"] in recs else None   # noqa: E731
    for s in srcs:
        k = key(s)
        if k:
            src_of.setdefault(board_of[s["src"]], set()).add(k)
            all_of.setdefault(board_of[s["src"]], set()).add(k)
    for s in own:
        k = key(s)
        if k:
            all_of.setdefault(s["src"], set()).add(k)
    return sh_of, src_of, all_of


def _nf():
    return CrmError("NOT-FOUND", "그 한판을 찾지 못했어요.", "루틴판의 쓰는 중 카드에서 다시 여세요.")


def routine_board_detail(uid, item_id, p=None):
    """한판 상세(구현계획 2-3). 반환 모양은 routine.sample.json 의 detail. 루틴판 설정이 없거나 한판 오브젝트가 없으면,
    또는 그 한판 오브젝트의 살아 있는 내 항목이 아니면 NOT-FOUND."""
    item_id = str(item_id or "")
    if p is None:
        p = routine_p(uid)
    if not p:
        raise _nf()
    with tx() as c:
        objs, missing = _objects(c, uid, p)
        o_wr = objs.get("writing")
        if not o_wr:
            raise _nf()
        b = _items(c, uid, o_wr["id"], [item_id])
        if not b:
            raise _nf()
        b = b[0]
        stf = _pair(p.get("stage"))[0] or F_STAGE
        stage = (b["data"] or {}).get(stf)
        board = {"item_id": b["id"], "title": b["title"], "key_line": _key_line(b),
                 "stage": stage if isinstance(stage, str) else None, "date": _day(b, o_wr["date_field"]).isoformat()}
        subs = []
        o_sh = objs.get("subheads")
        if o_sh:
            ids = [r["src"] for r in _all(c, "SELECT source_item_id AS src FROM item_links WHERE user_id=%s AND field_key=%s "
                                             "AND target_item_id=%s", (uid, F_BOARD, b["id"]))]
            subs = _items(c, uid, o_sh["id"], ids) if ids else []

        def order(r):
            v = (r["data"] or {}).get(F_ORDER)
            return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None
        subs.sort(key=lambda r: (order(r) is None, order(r) or 0, r["created_at"], r["id"]))
        sh_links = _links(c, uid, [r["id"] for r in subs], (F_SRC_POSTS, F_SRC_RECORDS))
        b_links = _links(c, uid, [b["id"]], (F_INFLOW, F_MATERIALS))
        all_links = sh_links + b_links
        items = _live_items(c, uid, {x["ti"] for x in all_links if x["ti"]})
        recs = _live_records(c, uid, {x["tr"] for x in all_links if x["tr"]})
        dfs = _date_fields(c, uid, {r["object_id"] for r in items.values()})
        o_dec = objs.get("decided")
        routes = _route_items(c, uid, o_dec["id"], list(recs)) if o_dec else {}
        vf = p.get("verdict")

    def post(i):
        r, d = items[i], items[i]["data"] or {}
        s = lambda k: d.get(k) if isinstance(d.get(k), str) else None   # noqa: E731
        return {"kind": "post", "id": i, "title": r["title"], "author": s(F_AUTHOR), "channel": s(F_CHANNEL),
                "date": _day(r, dfs.get(r["object_id"])).isoformat(), "ai_summary": s(F_AI_SUMMARY), "ai": True}

    def record(rid):
        r, it = recs[rid], (routes.get(rid) or [None])[0]
        item = None
        if it:
            v = (it["data"] or {}).get(vf) if vf else None
            item = {"object_key": o_dec["key"], "item_id": it["id"], "title": it["title"], "verdict": v if isinstance(v, str) else None}
        return {"kind": "record", "id": rid, "title": r["title"], "date": r["d"].isoformat(), "item": item}

    def refs(links):
        posts = [x["ti"] for x in links if x["ti"] in items]
        rids = [x["tr"] for x in links if x["tr"] in recs]
        return list(dict.fromkeys(posts)), list(dict.fromkeys(rids))

    subheads, inflow, decided = [], [], []
    for r in subs:
        ps, rs = refs([x for x in sh_links if x["src"] == r["id"]])
        inflow += ps
        decided += rs
        subheads.append({"item_id": r["id"], "order": order(r), "text": r["title"], "body": r["body"],
                         "sources": [post(i) for i in ps] + [record(i) for i in rs]})
    ps, rs = refs(b_links)
    inflow, decided = list(dict.fromkeys(inflow + ps)), list(dict.fromkeys(decided + rs))
    dead = {("item", x["ti"]) for x in all_links if x["ti"] and x["ti"] not in items} | \
        {("record", x["tr"]) for x in all_links if x["tr"] and x["tr"] not in recs}
    return {"board": board, "subheads": subheads, "inflow": [post(i) for i in inflow], "decided": [record(i) for i in decided],
            "missing_sources": len(dead)}
