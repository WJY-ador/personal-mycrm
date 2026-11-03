// 대조 한 장 — 판단 문장 + 근거 원문 + 남길지 정하기(남기기 · 고쳐서 남기기 · 반영 안 함) + 이동(이전 · 건너뛰기).
// 결정 버튼은 근거 원문을 확인한 뒤에만 켜지고, 저장 중(locked)엔 결정·편집·이동이 모두 잠긴다. 후보가 바뀌면 key 로 새로 그린다(편집 칸 닫힘).
import { useEffect, useRef, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiErr } from "../../shared/api";
import { fetchJournal, journalKey } from "../../shared/journal";
import { ReviewNote } from "../../shared/ReviewNote";
import type { AppState, Cand } from "../../shared/state";
import { quoteOk, Source } from "./Source";
import { NO_QUESTION, type Words } from "./text";
import css from "./Review.module.css";

type Props = {
  S: AppState; c: Cand; head: ReactNode; qText: string; byRec: boolean; oldNav: boolean; w: Words;
  prev: string; next: string; locked: boolean; status: string; err: string;
  onDecide: (action: string, text?: string) => void;
};

// 칩 — AI 문안(사용자가 아직 승인하지 않은 AI 문안, 옛 서버엔 키 없음) · 쓴 쪽(옛 origin·aiWordingChip 그대로)
function Labels({ c }: { c: Cand }) {
  return (
    <div className="labels"><span className="badge b-wait">아직 안 정함</span>
      <span className={`badge ${c.origin === "ai" ? "b-ai" : "b-memo"}`}>{c.origin === "ai" ? "AI가 쓴 문장" : "내가 쓴 메모"}{c.edited_by_user ? " · 내가 고침" : ""}</span>
      {c.wording_approved === false && c.wording_by === "ai" && <span className="chip o-ai">AI 문안</span>}</div>
  );
}

export function Card({ S, c, head, qText, byRec, oldNav, w, prev, next, locked, status, err, onDecide }: Props) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState(c.text);
  const ta = useRef<HTMLTextAreaElement>(null), eb = useRef<HTMLButtonElement>(null);
  const q = useQuery({ queryKey: journalKey(c.record_id), queryFn: () => fetchJournal(c.record_id) });
  const off = locked || !quoteOk(q.data, c);
  useEffect(() => { if (open) ta.current?.focus(); }, [open]);
  const cancel = () => { setOpen(false); setText(c.text); eb.current?.focus(); };
  const dest = byRec ? `남기면 ${w.mine}에 들어가요(${NO_QUESTION}).` : `남기면 「${qText}」의 ${w.mine}에 들어가요.`;
  return (
    <div className={css.review}>{head}
      <section className={css.card} data-candidate-id={c.id} aria-labelledby="candidate-title">
        <p className={css.q}>{byRec ? "" : "질문 · "}{qText}</p><h3 id="candidate-title" className="sr">{w.cardTitle}</h3><p className={css.sent}>{c.text}</p>
        <Labels c={c} /><ReviewNote review={c.review} oldNav={oldNav} />
      </section>
      <Source S={S} c={c} j={q.data} fail={q.isError ? apiErr(q.error) : null} w={w} />
      <section className={css.act} aria-labelledby="decision-title" aria-busy={locked}>
        <h3 id="decision-title">남길지 정하기</h3>
        <p id="decision-help" className={css.dest}>{`${dest} ${w.keepNote} 원문은 바뀌지 않아요.`}</p>
        <div className={`acts ${css.decide}`} id="rvacts" role="group" aria-label={w.group} aria-describedby="decision-help">
          <button className="secondary" type="button" disabled={off} onClick={() => onDecide("confirm")}>{w.confirm}</button>
          <button className="secondary" type="button" ref={eb} aria-expanded={open} aria-controls="rvedit" disabled={off} onClick={() => setOpen(!open)}>고쳐서 남기기</button>
          <button className="secondary" type="button" disabled={off} onClick={() => onDecide("exclude")}>반영 안 함</button></div>
        <form id="rvedit" className={css.edit} hidden={!open} aria-describedby="edit-help" onSubmit={e => { e.preventDefault(); onDecide("edit_confirm", text); }}>
          <label htmlFor="rvtext">{w.editLabel}</label><p id="edit-help" className="hint">{w.editHint} 원문은 바뀌지 않아요.</p>
          <textarea id="rvtext" ref={ta} name="text" rows={3} required value={text} onChange={e => setText(e.target.value)} />
          <div className="acts"><button className="primary" type="submit" disabled={locked}>고친 문장으로 남기기</button>
            <button className="tertiary" type="button" disabled={locked} onClick={cancel}>취소</button></div></form>
        <p id="save-status" className={css.status} role="status" aria-atomic="true">{status}</p>
        <p id="save-error" role="alert" aria-atomic="true" className="blocked">{err}</p>
      </section>
      <nav className={css.nav} aria-label={w.navLabel} aria-describedby="skip-help">
        <button className="tertiary" type="button" disabled={locked || !prev} onClick={() => { location.hash = prev; }}>이전 문장</button>
        <button className="tertiary" type="button" disabled={locked} onClick={() => { location.hash = next; }}>건너뛰기</button>
        <p id="skip-help" className="hint">건너뛰어도 아직 안 정한 문장으로 남아요.</p></nav>
    </div>
  );
}
