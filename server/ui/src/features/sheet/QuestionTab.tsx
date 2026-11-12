// 질문형 탭(옛 renderQuestionTab·pickQuestions·sheetSections·recentRecords) — 질문 고르기 줄 + 질문 한 장(확정한 판단 · 아직 안 정한 문장 · 반영 안 함 · 연결된 글).
// blocks = 탭이 고른 조각(sheet·candidates·next·journal). 결정은 판단 검토 화면([원문과 대조하기])에서만.
import { DecisionBadge, OriginBadge } from "../../shared/CandChips";
import { clip, qNo } from "../../shared/clip";
import { PartFail } from "../../shared/PartFail";
import { readOk, type AppState, type Question } from "../../shared/state";
import { EvLine, FirstRun, NextLine, RecRow, type Open } from "./parts";

type Props = { S: AppState; tabId: string; bl: Set<string>; sel: string; open: Open };
const fail = (S: AppState, part: string) => ({ code: "", msg: "", ...S.read?.[part]?.error });

function Sheet({ S, tabId, q, open }: { S: AppState; tabId: string; q: Question; open: Open }) {
  if (!readOk(S, "candidates")) return <section className="sec"><PartFail err={fail(S, "candidates")} what="문장 목록" /></section>;
  const cs = (S.candidates || []).filter(c => c.question_id === q.id);
  const mine = cs.filter(c => c.status === "confirmed"), wait = cs.filter(c => c.status === "pending"), off = cs.filter(c => c.status === "excluded");
  const recs = [...new Set(cs.map(c => c.record_id))];
  return (
    <>
      <section className="sec"><h3>확정한 판단<span className="count">{mine.length}</span></h3>
        {mine.length ? <div className="cards">{mine.map(c => <div className="card mine" key={c.id}><p className="sent">{c.text}</p>
          <div className="labels"><DecisionBadge status={c.status} /><OriginBadge c={c} /></div><EvLine S={S} c={c} open={open} /></div>)}</div>
          : <div className="empty">아직 확정한 판단이 없어요. 아래 문장을 원문과 대조해 남기면 여기에 쌓여요.</div>}</section>
      <section className="sec"><h3>아직 안 정한 문장<span className="count">{wait.length}</span></h3>
        {wait.length ? <><div className="cards">{wait.map(c => <div className="card cand" key={c.id}><p className="sent">{c.text}</p>
          <div className="labels"><OriginBadge c={c} /><DecisionBadge status={c.status} /></div></div>)}</div>
          <div className="cta"><p className="hint">남기기 전까진 확정한 판단이 아니에요.</p>
            <a className="btn primary" href={`#${tabId}/review/${q.id}/${wait[0].id}`}>원문과 대조하기({wait.length}개)</a></div></>
          : <div className="empty">{cs.length ? "정할 문장이 남아 있지 않아요." : "아직 이 질문에 뽑힌 문장이 없어요. 내 글에서 판단을 뽑으면 여기에 떠요."}</div>}</section>
      {off.length ? <details className="fold"><summary>반영 안 함 문장 보기({off.length}개)</summary><div className="cards">{off.map(c =>
        <div className="card cand" key={c.id}><p className="sent">{c.text}</p><div className="labels"><OriginBadge c={c} /><DecisionBadge status={c.status} /></div>
          <EvLine S={S} c={c} open={open} /></div>)}</div></details> : null}
      {recs.length ? <section className="sec"><h3>연결된 글<span className="count">{recs.length}</span></h3>
        <ul className="recs">{recs.map(r => <RecRow key={r} S={S} id={r} open={open} />)}</ul></section> : null}
    </>
  );
}

function Recent({ S, open }: { S: AppState; open: Open }) {
  if (!readOk(S, "journal")) return <section className="sec"><PartFail err={fail(S, "journal")} what="내 글 목록" /></section>;
  const js = (S.journal || []).slice(0, 8);
  return (
    <section className="sec"><h3>최근 글<span className="count">{(S.journal || []).length}</span></h3>
      {js.length ? <ul className="recs">{js.map(j => <RecRow key={j.id} S={S} id={j.id} open={open} />)}</ul> : <div className="empty">아직 내 글이 없어요.</div>}</section>
  );
}

export function QuestionTab({ S, tabId, bl, sel, open }: Props) {
  const qs = readOk(S, "questions") ? S.questions || [] : [];
  const q = qs.find(x => x.id === sel) || qs[0];
  const wait = (qid: string) => (S.candidates || []).filter(c => c.question_id === qid && c.status === "pending").length;
  const body = !readOk(S, "questions") ? <PartFail err={fail(S, "questions")} what="질문 목록" />
    : !q ? <FirstRun S={S} />
    : <><div className="eyebrow">질문 {qNo(S, q.id)}</div><h2 className="title">{q.text}</h2>
      {bl.has("next") ? <NextLine S={S} /> : null}
      {bl.has("sheet") || bl.has("candidates") ? <Sheet S={S} tabId={tabId} q={q} open={open} /> : null}
      {bl.has("journal") ? <Recent S={S} open={open} /> : null}</>;
  return (
    <>
      {qs.length ? <nav className="subtabs" aria-label="질문 고르기"><div className="wrap" style={{ padding: ".9rem 0 0" }}>{qs.map((x, i) => {
        const on = q?.id === x.id, w = wait(x.id);
        return <a key={x.id} href={`#${tabId}/${x.id}`} className={on ? "on" : ""} aria-current={on ? "true" : undefined} title={x.text}>
          Q{i + 1} {clip(x.text, 36)}{w ? <span className="n">{w}</span> : null}</a>;
      })}</div></nav> : null}
      <div className="paper sheet">{body}</div>
    </>
  );
}
