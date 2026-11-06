// 대조 한 장 — 판단 문장 + 근거 원문 + 남길지 정하기(남기기 · 고쳐서 남기기 · 반영 안 함) + 이동(이전 · 건너뛰기).
// 고친 문장이 기준 문장과 다르면 onDirty(true), 같아지거나·취소하거나·사라지면 onDirty(false)(미저장 보호 — 등록부는 화면이 갖는다).
// 기준 = 원래 문장, 고친 문장 저장(edit_confirm)이 성공하면(onDecide 의 saved) 그때 보낸 문장 — 다시 받기에 실패해 카드가 남아도 다시 고치면 다시 등록된다.
// 남기기·반영 안 함은 고친 문장을 저장하지 않는다 — 편집 칸이 열려 있어도 기준·등록은 그대로(취소·사라질 때 푼다).
// 결정 버튼은 근거 원문을 확인한 뒤에만 켜지고, 저장 중(locked)엔 결정·편집·이동이 모두 잠긴다. 후보가 바뀌면 key 로 새로 그린다(편집 칸 닫힘).
import { useEffect, useRef, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiErr } from "../../shared/api";
import { fetchJournal, journalKey } from "../../shared/journal";
import { AiWording, DecisionBadge, OriginBadge } from "../../shared/CandChips";
import { ReviewNote } from "../../shared/ReviewNote";
import type { AppState, Cand } from "../../shared/state";
import { quoteOk, Source } from "./Source";
import { NO_QUESTION, type Words } from "./text";
import css from "./Review.module.css";

type Props = {
  S: AppState; c: Cand; head: ReactNode; qText: string; byRec: boolean; w: Words;
  prev: string; next: string; locked: boolean; status: string; err: string;
  onDecide: (action: string, text: string | undefined, saved: () => void, baseRevision: number) => void;   // saved = 저장 성공 알림(다시 받기 전에 부른다) · baseRevision = 기준 문장의 revision
  onDirty?: (dirty: boolean) => void;
};

// 칩 — AI 문안(사용자가 아직 승인하지 않은 AI 문안, 옛 서버엔 키 없음) · 쓴 쪽(옛 origin·aiWordingChip 그대로)
function Labels({ c }: { c: Cand }) {
  return (
    <div className="labels"><DecisionBadge status="pending" />
      <OriginBadge c={c} />
      <AiWording c={c} /></div>
  );
}

export function Card({ S, c, head, qText, byRec, w, prev, next, locked, status, err, onDecide, onDirty }: Props) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState(c.text);
  // 기준 = 원래 문장, 저장에 성공하면 그때 보낸 문장. acked 가 바뀌면 화면이 푼 등록을 지금 상태로 다시 알린다(저장 중에 더 고쳤으면 다시 등록)
  // revision = 기준 문장을 받은 때의 revision — 고친 문장 저장(edit_confirm)은 이것으로 충돌 검사를 한다(고치는 동안 원격이 바뀌면 서버가 충돌로 막는다)
  const [baseline, setBaseline] = useState({ text: c.text, revision: c.revision, acked: 0 });
  const dirty = text !== baseline.text, report = useRef(onDirty);
  // 같은 후보의 원격 문장·revision 이 바뀌면 — 깨끗할 때만 편집 칸과 기준을 최신으로. 고치던 중이면 초안과 기준 revision 을 그대로 둔다
  useEffect(() => {
    if (dirty || c.revision <= baseline.revision) return;
    setText(c.text); setBaseline(b => ({ ...b, text: c.text, revision: c.revision }));
  }, [dirty, c.text, c.revision]);
  report.current = onDirty;   // 최신 콜백을 부른다 — 인라인 콜백이 다시 만들어져도 알림이 튀지 않게
  useEffect(() => { report.current?.(dirty); }, [dirty, baseline.acked]);
  useEffect(() => () => report.current?.(false), []);
  const ta = useRef<HTMLTextAreaElement>(null), eb = useRef<HTMLButtonElement>(null);
  const q = useQuery({ queryKey: journalKey(c.record_id), queryFn: () => fetchJournal(c.record_id) });
  const off = locked || !quoteOk(q.data, c);
  useEffect(() => { if (open) ta.current?.focus(); }, [open]);
  // 취소 = 초안을 버리고 최신 원격 문장·revision 을 기준으로
  const cancel = () => { setOpen(false); setText(c.text); setBaseline(b => ({ ...b, text: c.text, revision: c.revision })); eb.current?.focus(); };
  const decide = (action: string, t?: string) => {
    const sent = text;   // 저장을 누른 때의 문장 — edit_confirm 이 성공하면 이것이 새 기준(실패·충돌·다른 결정이면 기준 그대로, 고친 문장은 보호된다)
    onDecide(action, t, () => { if (action === "edit_confirm") setBaseline(b => ({ ...b, text: sent, acked: b.acked + 1 })); }, baseline.revision);
  };
  const dest = byRec ? `남기면 ${w.mine}에 들어가요(${NO_QUESTION}).` : `남기면 「${qText}」의 ${w.mine}에 들어가요.`;
  return (
    <div className={css.review}>{head}
      <section className={css.card} data-candidate-id={c.id} aria-labelledby="candidate-title">
        <p className={css.q}>{byRec ? "" : "질문 · "}{qText}</p><h3 id="candidate-title" className="sr">{w.cardTitle}</h3><p className={css.sent}>{c.text}</p>
        <Labels c={c} /><ReviewNote review={c.review} />
      </section>
      <Source S={S} c={c} j={q.data} fail={q.isError ? apiErr(q.error) : null} w={w} />
      <section className={css.act} aria-labelledby="decision-title" aria-busy={locked}>
        <h3 id="decision-title">남길지 정하기</h3>
        <p id="decision-help" className={css.dest}>{`${dest} ${w.keepNote} 원문은 바뀌지 않아요.`}</p>
        <div className={`acts ${css.decide}`} id="rvacts" role="group" aria-label={w.group} aria-describedby="decision-help">
          <button className="secondary" type="button" disabled={off} onClick={() => decide("confirm")}>{w.confirm}</button>
          <button className="secondary" type="button" ref={eb} aria-expanded={open} aria-controls="rvedit" disabled={off} onClick={() => setOpen(!open)}>고쳐서 남기기</button>
          <button className="secondary" type="button" disabled={off} onClick={() => decide("exclude")}>반영 안 함</button></div>
        <form id="rvedit" className={css.edit} hidden={!open} aria-describedby="edit-help" onSubmit={e => { e.preventDefault(); decide("edit_confirm", text); }}>
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
