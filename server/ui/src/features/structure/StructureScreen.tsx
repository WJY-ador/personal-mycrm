// 구조 화면(옛 renderStructure·structViews·renderCandGallery) — #structure/<정의 id>[/<항목 id>] · #structure/cand/<결정 필터>(옛 #structure/confirmed 등도).
// 보기 전환(항목 · 내 구조 설정) → 정의 필(기준 → 판단 문장 → 그 밖) → 카드 그리드 + 오른쪽 서랍. 적용된 항목 하나 주소는 껍데기가 「나」로 옮긴다(navReplace).
import { useState } from "react";
import type { ScreenProps } from "../../shared/ctx";
import { byNewest } from "../../shared/clip";
import { PartFail } from "../../shared/PartFail";
import { useRecDialog } from "../../shared/RecDialog";
import { readOk } from "../../shared/state";
import { AssetCard, ItemCard } from "./Cards";
import { Drawer } from "./Drawer";
import { defById, FILTERS, NOCARD, TAB } from "./model";

const Pill = ({ href, label, n, on, cls = "n m" }: { href: string; label: string; n: number; on: boolean; cls?: string }) =>
  <a href={href} className={on ? "on" : ""} aria-current={on ? "true" : undefined}>{label}<span className={cls}>{n}</span></a>;

export function StructureScreen({ ctx }: ScreenProps) {
  const S = ctx.state!, [a = "", b = ""] = ctx.args || [];
  const rec = useRecDialog(S);
  const [msg, setMsg] = useState<{ at: string; text: string } | null>(null);   // 서랍이 사라진 뒤(새 제안 제외·삭제) 빈 서랍에 한 번
  const ds = S.definitions || [], rules = ds.filter(d => d.semantic_kind === "principle"), others = ds.filter(d => d.semantic_kind !== "principle");
  const cs = readOk(S, "candidates") ? S.candidates || [] : [];
  let sel = a, filter = "";
  if (FILTERS.some(x => x[0] === a)) { sel = "cand"; filter = a; } else if (a === "cand") filter = b;
  if (sel !== "cand" && !defById(S, sel)) sel = rules[0] ? rules[0].id : "cand";
  if (!FILTERS.some(x => x[0] === filter)) filter = "confirmed";
  const cnt = (id: string) => (S.items || []).filter(it => it.object_id === id).length;
  const views = <nav className="pills sview" aria-label="구조 보기"><a href={`#${TAB}`} className="on" aria-current="true">항목</a><a href="#_settings/structure">내 구조 설정</a></nav>;
  const sub = <nav className="pills sobjs" aria-label="구조 고르기">{rules.map(d => <Pill key={d.id} href={`#${TAB}/${d.id}`} label={d.label} n={cnt(d.id)} on={sel === d.id} />)}
    <Pill href={`#${TAB}/cand/${filter}`} label="판단 문장" n={cs.length} on={sel === "cand"} />
    {others.map(d => <Pill key={d.id} href={`#${TAB}/${d.id}`} label={d.label} n={cnt(d.id)} on={sel === d.id} />)}</nav>;
  let body;
  if (sel === "cand") {
    if (!readOk(S, "candidates")) body = <PartFail err={{ code: "", msg: "", ...S.read?.candidates?.error }} what="문장 목록" />;
    else {
      const list = cs.filter(c => filter === "all" || c.status === filter).sort(byNewest);
      body = <><nav className="pills" aria-label="결정 고르기">{FILTERS.map(([k, l]) =>
        <Pill key={k} href={`#${TAB}/cand/${k}`} label={l} n={k === "all" ? cs.length : cs.filter(c => c.status === k).length} on={k === filter} cls="n" />)}</nav>
        {list.length ? <div className="gallery">{list.map(c => <AssetCard key={c.id} S={S} c={c} open={rec.open} />)}</div> : <div className="empty">{NOCARD[filter]}</div>}</>;
    }
  } else {
    const d = defById(S, sel)!, mine = (x: { object_id: string }) => x.object_id === d.id;
    const items = [...(S.item_proposals || []).filter(mine), ...(S.items || []).filter(mine)];
    const open = b && (S.items || []).concat(S.item_proposals || []).some(x => x.id === b) ? b : "";
    const here = location.hash;
    body = <div className="struct"><div>{items.length ? <div className="gallery">{items.map(it => <ItemCard key={it.id} S={S} it={it} d={d} on={open === it.id} />)}</div>
      : <div className="empty">아직 {d.label} 항목이 없어요. 연결한 AI 대화에서 제안하면 여기서 적용할 수 있어요.</div>}</div>
      <aside id="panel" aria-label={`${d.label} 서랍`} aria-live="polite">{open
        ? <Drawer key={open} ctx={ctx} S={S} id={open} open={rec.open} gone={(text, to) => { setMsg({ at: to, text }); location.replace(to); }} />
        : msg && msg.at === here ? <p className="pstatus" role="status">{msg.text}</p> : <p className="empty">카드를 누르면 여기 떠요.</p>}</aside></div>;
  }
  return <>{views}{sub}{body}{rec.dialog}</>;
}
