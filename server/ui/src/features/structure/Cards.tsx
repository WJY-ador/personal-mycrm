// 구조 카드(옛 itemCard·assetCard·selectChips·decisionChip) — 항목 카드(누르면 서랍) · 판단 문장 카드(아직 안 정함 = 대조, 정한 문장 = 근거 원문).
import { AiWording } from "../../shared/CandChips";
import { Caution } from "../../shared/Glyph";
import { qNo, reviewHref } from "../../shared/clip";
import { md } from "../../shared/date";
import { press } from "../../shared/press";
import { rich } from "../../shared/rich";
import type { AppState, Cand, Def, Item } from "../../shared/state";
import { dataSummary, eventLabel, incomingCounts, linkCount, promoOf, STCHIP, TAB, viewOf } from "./model";


export function SelectChips({ it, d }: { it: Item; d: Def | undefined }) {
  return <>{((d && d.fields) || []).filter(f => f.value_type === "select" && it.data && it.data[f.key] != null && it.data[f.key] !== "").map(f => {
    const v = it.data![f.key], o = (f.options || []).find(x => x.value === v);
    return <span key={f.key} className="chip" title={f.label}>{o ? o.label : String(v)}</span>;
  })}</>;
}

export function DecisionChip({ it }: { it: Item }) {
  if (it.semantic_kind !== "principle" || !it.revision) return null;
  const st = STCHIP[it.decision || ""] || STCHIP.pending;
  return <span className={`chip ${st[0]}`}>{st[1]}</span>;
}

export function ItemCard({ S, it, d, on }: { S: AppState; it: Item; d: Def; on: boolean }) {
  const p = promoOf(d), isNew = !it.revision, v = viewOf(it), inc = incomingCounts(S, it.id);
  const summary = d.semantic_kind === "principle" ? v.body : dataSummary(v, d) || v.body;
  return (
    <article className={`asset-card${isNew ? " new" : ""}${on ? " on" : ""}`} {...press(() => { location.hash = `#${TAB}/${d.id}/${it.id}`; })}>
      <div className="top">{v.code ? <span className="chip code">{v.code}</span> : null}<SelectChips it={v} d={d} /><DecisionChip it={it} />
        {it.promotion?.met ? <span className="chip promo-met" title="승격 조건 충족 — 남길지는 내가 정해요">승격</span> : null}
        {p ? <span className="chip">근거 {linkCount(v, p.claim_field)}</span> : null}
        {p?.event_field ? <span className="chip">{eventLabel(S, d)} {linkCount(v, p.event_field)}</span> : null}
        {isNew ? <span className="chip flag">새 제안</span> : it.proposal ? <span className="chip flag">제안 있음</span> : null}</div>
      <h3>{v.title || "(제목 없음)"}</h3>{summary ? <p className="summary">{summary}</p> : null}
      <div className="meta"><span>{md(it.updated_at)}</span>{Object.entries(inc).map(([k, n]) => <span key={k}>{k} {n}</span>)}</div></article>
  );
}

export function AssetCard({ S, c, open }: { S: AppState; c: Cand; open: (id: string, quote?: string) => void }) {
  const st = STCHIP[c.status] || STCHIP.pending, r = (S.journal || []).find(j => j.id === c.record_id);
  const title = !r ? "찾을 수 없는 글" : r.broken ? "읽지 못한 글" : r.title;
  // 아직 안 정한 문장은 대조 화면으로, 정한 문장은 근거 원문으로
  const go = c.status === "pending" ? () => { location.hash = reviewHref(TAB, c); } : () => open(c.record_id, c.quote);
  return (
    <article className="asset-card" {...press(go)}>
      <div className="top"><span className="chip">{qNo(S, c.question_id)}</span><span className={`chip ${st[0]}`}>{st[1]}</span>
        <span className={`chip${c.origin === "ai" ? " o-ai" : ""}`}>{c.origin === "ai" ? "AI가 쓴 문장" : "내가 쓴 메모"}</span>
        {c.edited_by_user ? <span className="chip st-mine">내가 고침</span> : null}{c.status === "pending" && c.origin === "ai" ? <span className="chip flag"><Caution />AI 미확정</span> : null}
        <AiWording c={c} /></div>
      <h3>{c.text}</h3>
      <p className="summary"><mark>{rich(c.quote)}</mark></p>
      <div className="meta"><span>{md(c.created)}</span><a {...press(() => open(c.record_id, c.quote))} onClick={e => { e.stopPropagation(); open(c.record_id, c.quote); }}>{title}</a></div></article>
  );
}
