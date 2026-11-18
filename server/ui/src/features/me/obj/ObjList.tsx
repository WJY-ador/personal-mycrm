// 목록 보기(List View) — 서버가 거르고 정렬해 50행씩(GET /api/me/objects/<key>). 열 = 제목 + 필드 앞 최대 5개(+ 수집 글 상태).
// 열 머리 = 정렬(오름·내림) · 칩 = 선택 목록 필드마다 값 하나(건수 = 그 오브젝트 전체) + 상태 · 제목 검색 · 「더 보기」.
// 좁은 화면 = 카드(제목 + 앞 두 필드). 껍데기가 상태를 다시 받으면(S.generated) 목록도 다시 받는다(쓰기 뒤 낡은 목록 방지).
import { useEffect, useState } from "react";
import { keepPreviousData, useInfiniteQuery } from "@tanstack/react-query";
import type { Def } from "../../../shared/state";
import { fieldText } from "../FieldRows";
import { meApi, type ObjCol, type ObjList as List, type ObjQuery, type ObjRow } from "../meApi";
import type { World } from "../model";
import { LOADING, ME_EMPTY, OBJ_STATE, OBJ_TEXT } from "../text";
import { backNav, useMobile } from "../view";
import { objHref } from "./ObjTab";
import css from "./Obj.module.css";

type Props = { W: World; def: Def; vq: ObjQuery; setVq: (q: ObjQuery) => void };
const STATE_COL: ObjCol = { key: "state", label: OBJ_TEXT.state, value_type: "select", options: OBJ_STATE.map(([value, label]) => ({ value, label })) };
// 글자 필드 값이 https:// 로 시작하면 칸에는 「원문」 한 낱말 링크(새 탭) — 긴 주소를 늘어놓지 않는다. 키 이름이 아니라 값으로 판정한다
const href = (c: ObjCol, v: unknown) => (c.value_type === "text" && typeof v === "string" && v.startsWith("https://") ? v : "");
const cell = (c: ObjCol, r: ObjRow) => (c.key === "state" ? fieldText(STATE_COL, r.state) : href(c, r.data[c.key]) ? OBJ_TEXT.link : fieldText(c, r.data[c.key]));
const td = (c: ObjCol, r: ObjRow) => (href(c, r.data[c.key])
  ? <a href={href(c, r.data[c.key])} target="_blank" rel="noopener noreferrer">{OBJ_TEXT.link}</a> : cell(c, r));
const firstDir = (c: ObjCol | null) => (c && (c.value_type === "date" || c.value_type === "number") ? "desc" : "asc");

function Chips({ label, vals, cur, pick }: { label: string; vals: { value: string; label: string; n: number }[]; cur: string; pick: (v: string) => void }) {
  const shown = vals.filter(v => v.n > 0 || v.value === cur);
  if (!shown.length) return null;
  return (
    <div className={css.chips} role="group" aria-label={label}><span className={css.cl}>{label}</span>
      {shown.map(v => <button key={v.value} type="button" className={`chip ${css.chip}`} aria-pressed={v.value === cur}
        onClick={() => pick(v.value === cur ? "" : v.value)}>{v.label} <span className={css.n}>{v.n}</span></button>)}
    </div>
  );
}

export function ObjList({ W, def, vq, setVq }: Props) {
  const mobile = useMobile();
  const [draft, setDraft] = useState(vq.q);
  useEffect(() => {
    if (draft === vq.q) return;
    const t = setTimeout(() => setVq({ ...vq, q: draft }), 250);
    return () => clearTimeout(t);
  }, [draft, vq, setVq]);
  const L = useInfiniteQuery({
    queryKey: ["me", "obj", def.key, vq, W.S.generated || ""],
    queryFn: ({ pageParam }) => meApi.objList(def.key, vq, pageParam),
    initialPageParam: "", getNextPageParam: (p: List) => p.next_cursor ?? undefined, placeholderData: keepPreviousData,
  });
  const first = L.data?.pages[0];
  const rc = def.policy?.route ? def.route_counts : undefined;   // 자동 분류 한 줄 — 담을 규칙이 있는 오브젝트만(건수 = /api/state definitions 그대로)
  const head = <><div className="htools"><h3 id="obj-list-h">{def.label}</h3><span className={css.count}>{first ? first.total : ""}</span></div>
    {rc ? <p className="hint" id="obj-route">{OBJ_TEXT.routed(rc.routed, rc.partial)}</p> : null}</>;
  if (!first) return (
    <section className={`paper hlist ${css.wrap}`} aria-labelledby="obj-list-h">{head}
      {L.isError ? <div className="empty">{OBJ_TEXT.fail} <button type="button" className="tertiary" onClick={() => void L.refetch()}>{OBJ_TEXT.retry}</button></div>
        : <p className="hint">{LOADING}</p>}
    </section>);
  const rows = L.data!.pages.flatMap(p => p.rows);
  const cols = first.has_state ? [...first.columns, STATE_COL] : first.columns;
  const filtered = !!(vq.q.trim() || vq.state || Object.values(vq.f).some(Boolean));
  const sortBy = (k: string, c: ObjCol | null) => setVq({ ...vq, sort: k, dir: first.sort.key === k ? (first.sort.dir === "asc" ? "desc" : "asc") : firstDir(c) });
  const go = () => { backNav.fromList = true; backNav.y = window.scrollY; };
  const th = (k: string, label: string, c: ObjCol | null) => {
    const on = first.sort.key === k;
    return <th key={k} scope="col" aria-sort={on ? (first.sort.dir === "asc" ? "ascending" : "descending") : undefined}>
      <button type="button" className={css.sort} onClick={() => sortBy(k, c)}>{label}<span aria-hidden="true">{on ? (first.sort.dir === "asc" ? " ▲" : " ▼") : ""}</span></button></th>;
  };
  return (
    <section className={`paper hlist ${css.wrap}`} aria-labelledby="obj-list-h" id="obj-list">{head}
      <div className={css.bar}>
        <input type="search" className={css.q} aria-label={OBJ_TEXT.search} placeholder={OBJ_TEXT.search} value={draft} onChange={e => setDraft(e.target.value)} />
        {first.states && <Chips label={OBJ_TEXT.state} cur={vq.state} pick={v => setVq({ ...vq, state: v })}
          vals={OBJ_STATE.map(([value, label]) => ({ value, label, n: first.states![value] || 0 }))} />}
        {first.filters.map(f => <Chips key={f.key} label={f.label} vals={f.values} cur={vq.f[f.key] || ""} pick={v => setVq({ ...vq, f: { ...vq.f, [f.key]: v } })} />)}
      </div>
      {!rows.length ? <div className="empty">{filtered ? OBJ_TEXT.none : ME_EMPTY}</div> : mobile ? (
        <ul className={css.cards}>{rows.map(r => <li key={r.id}><a href={objHref(def.key, r.id)} onClick={go}>
          <span className={css.ct}>{r.code && <span className={css.cd}>{r.code} </span>}{r.title || "(제목 없음)"}</span>
          <span className={css.cm}>{cols.slice(0, 2).map(c => cell(c, r)).filter(Boolean).join(", ")}</span></a></li>)}</ul>
      ) : (
        <div className={css.tw}><table className={css.tbl}>
          <thead><tr>{th("title", OBJ_TEXT.title, null)}{cols.map(c => th(c.key, c.label, c))}</tr></thead>
          <tbody>{rows.map(r => <tr key={r.id} onClick={e => { if (!(e.target as Element).closest("a")) { go(); location.hash = objHref(def.key, r.id); } }}>
            <td className={css.tt}><a href={objHref(def.key, r.id)} onClick={go}>{r.code && <span className={css.cd}>{r.code} </span>}{r.title || "(제목 없음)"}</a></td>
            {cols.map(c => <td key={c.key}>{td(c, r)}</td>)}</tr>)}</tbody>
        </table></div>
      )}
      {L.hasNextPage && <p className={css.more}><button type="button" className="secondary" disabled={L.isFetchingNextPage} onClick={() => void L.fetchNextPage()}>{OBJ_TEXT.more}</button></p>}
    </section>
  );
}
