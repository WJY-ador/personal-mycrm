// 지도(옛 renderMap) — 칸반 세 열: 들어오는 것(판단이 없는 글) · 내 손 대기(아직 안 정한 문장 → 대조) · 쌓이는 재료(확정 기준 + 확정한 판단).
// #_setup/map. ctx.args = [탭 id](대조 경로의 탭 — 옛 BASE.map = "map"). 보기만 — 결정은 판단 검토에서.
import type { ReactNode } from "react";
import type { ScreenProps } from "../../shared/ctx";
import { byNewest, clip, qNo, reviewHref } from "../../shared/clip";
import { md } from "../../shared/date";
import { PartFail } from "../../shared/PartFail";
import { useRecDialog } from "../../shared/RecDialog";
import { srcText } from "../../shared/source";
import { readOk, type Cand } from "../../shared/state";

const Col = ({ title, n, hint, cards }: { title: string; n: number; hint: string; cards: ReactNode[] }) => (
  <section className="kcol"><h2>{title} <span className="count">{n}</span></h2><p className="khint">{hint}</p>{cards.length ? cards : <div className="kempty">비어 있어요</div>}</section>
);

export function MapScreen({ ctx }: ScreenProps) {
  const S = ctx.state!, [tabId = "map"] = ctx.args || [];
  const rec = useRecDialog(S);
  if (!readOk(S, "candidates") || !readOk(S, "journal")) {
    const c = readOk(S, "candidates");
    return <PartFail err={{ code: "", msg: "", ...S.read?.[c ? "journal" : "candidates"]?.error }} what={c ? "내 글 목록" : "문장 목록"} />;
  }
  const cs = S.candidates || [], js = S.journal || [], used = new Set(cs.map(c => c.record_id));
  const inbox = js.filter(j => !used.has(j.id)), wait = cs.filter(c => c.status === "pending"), mine = cs.filter(c => c.status === "confirmed").sort(byNewest);
  const rules = (S.items || []).filter(it => it.semantic_kind === "principle" && it.decision === "confirmed");
  const label = (id: string) => (S.definitions || []).find(d => d.id === id)?.label || "항목";
  const src = (c: Cand) => <button type="button" onClick={() => rec.open(c.record_id, c.quote)}>원문</button>;
  const flags = (c: Cand) => <div className="kflags"><span className={`kflag${c.origin === "ai" ? "" : " memo"}`}>{c.origin === "ai" ? "AI가 쓴 문장" : "내가 쓴 메모"}</span>
    {c.edited_by_user ? <span className="kflag memo">내가 고침</span> : null}</div>;
  const rule = (S.definitions || []).find(d => d.semantic_kind === "principle")?.label || "기준";
  return (
    <>
      <div className="kanban">
        <Col title="들어오는 것" n={inbox.length} hint="AI 대화에서 검토할 판단을 뽑으면 다음 열로" cards={inbox.map(j => <div className="kcard" key={j.id}><div className="kname">{j.broken ? "읽지 못한 글" : j.title}</div>
          <div className="kmeta"><span>{md(j.created)}</span><span>{srcText(S.sources, j.source_id)}</span></div>
          <div className="kacts"><button type="button" onClick={() => rec.open(j.id)}>원문</button></div></div>)} />
        <Col title="내 손 대기" n={wait.length} hint="원문과 대조해 정해요" cards={wait.map(c => <div className="kcard hot" key={c.id}><div className="kname">{c.text}</div>{flags(c)}
          <div className="kacts">{src(c)}<a className="btn" href={reviewHref(tabId, c)}>대조</a></div></div>)} />
        <Col title="쌓이는 재료" n={mine.length + rules.length} hint={`내가 남긴 판단과 ${rule}`} cards={[...rules.map(it => <div className="kcard mine" key={it.id}><div className="kname">{it.title}</div>
          <div className="kflags"><span className="kflag memo">{label(it.object_id)}</span>{it.code ? <span className="kflag memo">{it.code}</span> : null}</div>
          <div className="kmeta"><span>{md(it.updated_at)}</span></div>
          <div className="kacts"><a className="btn" href={`#structure/${it.object_id}/${it.id}`}>보기</a></div></div>),
          ...mine.map(c => { const q = (S.questions || []).find(x => x.id === c.question_id); return <div className="kcard mine" key={c.id}><div className="kname">{c.text}</div>
            <div className="kmeta"><span title={q ? q.text : ""}>{qNo(S, c.question_id)} {clip(q ? q.text : "", 20)}</span><span>{md((c as { updated?: string }).updated || c.created)}</span></div>
            <div className="kacts">{src(c)}</div></div>; })]} />
      </div>
      {rec.dialog}
    </>
  );
}
