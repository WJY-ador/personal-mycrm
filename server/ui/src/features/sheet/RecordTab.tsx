// 기록형 탭(옛 renderRecordTab·srcFilter·srcChip·axisChips) — 왼쪽: 고른 글 원문 + 이 글에서 나온 문장 / 오른쪽: 다른 글(최근 12).
// 출처 필터(전부 · 출처마다 · 출처 미확인)는 화면에 머무는 동안 기억한다(옛 recSrc). 개수는 전체 글 기준(source_counts).
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiErr } from "../../shared/api";
import { DecisionBadge, OriginBadge } from "../../shared/CandChips";
import { dayParts, mdhm } from "../../shared/date";
import { Doc } from "../../shared/Doc";
import { fetchJournal, journalKey } from "../../shared/journal";
import { PartFail } from "../../shared/PartFail";
import { ReviewNote } from "../../shared/ReviewNote";
import { SRC_KIND, SRC_NONE, srcLine, srcText } from "../../shared/source";
import { readOk, type AppState, type Rec } from "../../shared/state";
import { press } from "../../shared/press";
import { FirstRun, NextLine } from "./parts";

let remembered = "all";   // 옛 recSrc — 같은 페이지 안에서 탭을 오가도 고른 출처 유지

function SrcChip({ S, r }: { S: AppState; r: Rec }) {
  const x = r.source_id ? (S.sources || []).find(s => s.id === r.source_id) : undefined;
  return x ? <span className="chip src" title={x.location || ""}>{srcText(S.sources, r.source_id)}</span> : <span className="chip src none">{SRC_NONE}</span>;
}

function AxisChips({ S, rid }: { S: AppState; rid: string }) {
  const ls = (S.record_links || []).filter(l => l.record_id === rid && l.field_key === "axes");
  if (!ls.length) return null;
  const all = (S.items || []).concat(S.item_proposals || []);
  return <><span className="axl">붙은 축</span>{ls.map((l, i) => {
    const it = l.target_kind === "item" ? all.find(x => x.id === l.target_id) : undefined;
    const d = it && (S.definitions || []).find(x => x.id === it.object_id);
    return <span key={i} className="chip axis" title={it ? (d ? d.label : "항목") : undefined}>{it ? it.title || "(제목 없음)" : "찾을 수 없는 항목"}</span>;
  })}</>;
}

function Body({ S, j }: { S: AppState; j: Rec }) {
  const q = useQuery({ queryKey: journalKey(j.id), queryFn: () => fetchJournal(j.id) });
  const qText = (id: string) => (S.questions || []).find(x => x.id === id)?.text || null;
  if (q.isError && !q.data) return <PartFail err={apiErr(q.error)} what="이 글" />;
  if (!q.data) return <div className="doc"><p className="dim">원문을 불러오는 중이에요…</p></div>;
  const r = q.data;
  return <>{q.isError ? <PartFail err={apiErr(q.error)} what="이 글" /> : null}<div className="recmeta">{mdhm(r.meta.created)} · {srcLine(S.sources, j.source_id, r.meta.source)}</div><Doc title={r.title} body={r.body} qText={qText} /></>;
}

export function RecordTab({ S, tabId, bl, sel }: { S: AppState; tabId: string; bl: Set<string>; sel: string }) {
  const [src, setSrcState] = useState(remembered);
  const setSrc = (k: string) => { remembered = k; setSrcState(k); };
  const all = readOk(S, "journal") ? S.journal || [] : [];
  const cnt = S.source_counts || { by_source: {}, unconfirmed: 0 }, by = cnt.by_source || {};
  const total = Object.values(by).reduce((a, n) => a + n, 0) + (cnt.unconfirmed || 0);
  const opts: [string, string, number][] = [["all", "전부", total], ...(S.sources || []).map(x => [x.id, `${x.name} · ${SRC_KIND[x.kind] || x.kind}`, by[x.id] || 0] as [string, string, number]),
    ["none", SRC_NONE, cnt.unconfirmed || 0]];
  const cur = opts.some(o => o[0] === src) ? src : "all";   // 없는 출처를 고른 상태면 「전부」로
  const has = (r: Rec) => !!(r.source_id && (S.sources || []).some(s => s.id === r.source_id));
  const js = all.filter(r => cur === "all" || (cur === "none" ? !has(r) : r.source_id === cur));
  const j = js.find(x => x.id === sel) || js[0];
  const filt = all.length ? <><nav className="pills srcf" aria-label="출처별 보기">{opts.map(([k, l, n]) => (
      <a key={k} {...press(() => setSrc(k))} aria-pressed={k === cur} className={k === cur ? "on" : ""}>{l}<span className="n">{n}</span></a>))}</nav>
    {total > all.length ? <p className="hint">목록엔 글 {all.length}편까지 보여요. 개수는 전체 글 기준이에요.</p> : null}</> : null;
  let body;
  if (!readOk(S, "journal")) body = <PartFail err={{ code: "", msg: "", ...S.read?.journal?.error }} what="내 글 목록" />;
  else if (!all.length) body = <FirstRun S={S} />;
  else if (!j) body = <>{filt}<div className="empty">불러온 글 중에 이 출처에서 온 글이 없어요.</div></>;
  else {
    const cs = (S.candidates || []).filter(c => c.record_id === j.id), q = (S.questions || []).find(x => x.id === j.question_id);
    body = <>{filt}<div className="eyebrow">내 글{q ? ` · ${q.text}` : ""}</div><h2 className="title">{j.broken ? "읽지 못한 글" : j.title}</h2>
      <div className="labels"><SrcChip S={S} r={j} /><AxisChips S={S} rid={j.id} /></div>
      {bl.has("next") ? <NextLine S={S} /> : null}
      <div id="recbody"><Body key={j.id} S={S} j={j} /></div>
      {(bl.has("candidates") || bl.has("sheet")) && cs.length ? <section className="sec"><h3>이 글에서 나온 문장<span className="count">{cs.length}</span></h3>
        <div className="cards">{cs.map(c => <div key={c.id} className={`card ${c.status === "confirmed" ? "mine" : "cand"}`}><p className="sent">{c.text}</p>
          <div className="labels"><DecisionBadge status={c.status} /><OriginBadge c={c} /></div><ReviewNote review={c.review} /></div>)}</div></section> : null}</>;
  }
  if (!j || js.length <= 1) return <div className="paper sheet">{body}</div>;
  return (
    <div className="board"><div className="paper">{body}</div><aside className="rside" aria-label="다른 글">
      <h2 className="sh">다른 글 <span className="speclabel">{js.length - 1}</span></h2>
      <div className="recbox"><ul className="recs">{js.filter(x => x.id !== j.id).slice(0, 12).map(x => { const dp = dayParts(x.created); return (
        <li key={x.id}><a href={`#${tabId}/${x.id}`}><div className="d">{dp.d}<small>{dp.mo ? dp.mo + "월" : ""}</small></div>
          <div><div className="t">{x.broken ? "읽지 못한 글" : x.title}</div><div className="s">{x.excerpt || ""}</div>
            <div className="srcl"><SrcChip S={S} r={x} /><AxisChips S={S} rid={x.id} /></div></div></a></li>); })}</ul></div></aside></div>
  );
}
