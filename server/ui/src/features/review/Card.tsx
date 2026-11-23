// 대조 카드 하나 — 판단 문장(눌러서 고치기) + 근거 원문 + [남기기] [남기지 않기]. 목록에 여럿이 놓이므로 id 는 모두 후보 id 를 붙인다.
// 문장을 누르면(Enter, Space 포함) 문장과 쓴 쪽 표시 아래에 편집 칸이 열린다. [고친 문장으로 남기기] = edit_confirm, [취소]와 Esc = 초안을 버린다.
// 편집 칸이 열린 동안엔 이 카드의 [남기기] [남기지 않기]를 숨긴다(보이는 버튼은 편집 칸의 둘뿐, 취소하면 다시 보인다).
// 고친 문장이 기준 문장과 다르면 onDirty(true), 같아지거나, 취소하거나, 사라지면 onDirty(false)(미저장 보호 — 등록부는 화면이 갖는다).
// 기준 = 원래 문장, 고친 문장 저장(edit_confirm)이 성공하면(onDecide 의 saved) 그때 보낸 문장 — 다시 받기에 실패해 카드가 남아도 다시 고치면 다시 등록된다.
// 남기기, 남기지 않기는 고친 문장을 저장하지 않는다 — 편집 칸이 열려 있어도 기준과 등록은 그대로(취소하거나 사라질 때 푼다).
// 결정(문장 고치기 포함)은 근거 원문을 확인한 뒤에만 켜지고, 저장 중(locked)엔 결정과 편집이 모두 잠긴다.
import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiErr } from "../../shared/api";
import { fetchJournal, journalKey } from "../../shared/journal";
import { AiWording, OriginBadge } from "../../shared/CandChips";
import { EditMark } from "../../shared/EditMark";
import { ReviewNote } from "../../shared/ReviewNote";
import type { AppState, Cand } from "../../shared/state";
import { quoteOk, Source } from "./Source";
import type { Words } from "./text";
import ed from "../../shared/Edit.module.css";
import css from "./Review.module.css";

type Props = {
  S: AppState; c: Cand; n: number; w: Words; locked: boolean;
  lead: string; status: string; err: string;   // lead = 앞 카드가 빠진 결과 한 줄(이 카드 위), status, err = 이 카드의 저장 문구
  onDecide: (action: string, text: string | undefined, saved: () => void, baseRevision: number) => void;   // saved = 저장 성공 알림(다시 받기 전에 부른다) · baseRevision = 기준 문장의 revision
  onDirty?: (dirty: boolean) => void;
};

// 쓴 쪽 표시 — 이 화면의 판단은 모두 아직 안 정한 것이라 결정 배지를 두지 않는다(머리의 "아직 안 정한 문장 N개"가 말한다).
// AI 표시는 하나만(디자인 2 C3): 쓴 쪽이 AI면 그 배지, 아니면 승인 전 AI 문안 칩(옛 서버엔 키 없음). aiMark = 그 표시가 있는지(점선 세로줄도 이때만)
const aiMark = (c: Cand) => c.origin === "ai" || (c.wording_approved === false && c.wording_by === "ai");
function Labels({ c }: { c: Cand }) {
  return (
    <div className="labels"><OriginBadge c={c} />
      {c.origin === "ai" ? null : <AiWording c={c} />}</div>
  );
}

// 연필이 마지막 낱말과 같은 줄에 붙게 — 마지막 낱말(뒤 공백 포함)과 연필을 줄바꿈 없는 한 덩이로. 글자는 그대로(textContent = 문장)
function lastWord(t: string) {
  const m = /^([\s\S]*?)(\S+\s*)$/.exec(t);
  return m ? <>{m[1]}<span className={css.tail}>{m[2]}<EditMark /></span></> : <>{t}<EditMark /></>;
}

export function Card({ S, c, n, w, locked, lead, status, err, onDecide, onDirty }: Props) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState(c.text);
  // 기준 = 원래 문장, 저장에 성공하면 그때 보낸 문장. acked 가 바뀌면 화면이 푼 등록을 지금 상태로 다시 알린다(저장 중에 더 고쳤으면 다시 등록)
  // revision = 기준 문장을 받은 때의 revision — 고친 문장 저장(edit_confirm)은 이것으로 충돌 검사를 한다(고치는 동안 원격이 바뀌면 서버가 충돌로 막는다)
  const [baseline, setBaseline] = useState({ text: c.text, revision: c.revision, acked: 0 });
  const dirty = text !== baseline.text, report = useRef(onDirty);
  // 같은 후보의 원격 문장, revision 이 바뀌면 — 깨끗할 때만 편집 칸과 기준을 최신으로. 고치던 중이면 초안과 기준 revision 을 그대로 둔다
  useEffect(() => {
    if (dirty || c.revision <= baseline.revision) return;
    setText(c.text); setBaseline(b => ({ ...b, text: c.text, revision: c.revision }));
  }, [dirty, c.text, c.revision]);
  report.current = onDirty;   // 최신 콜백을 부른다 — 인라인 콜백이 다시 만들어져도 알림이 튀지 않게
  useEffect(() => { report.current?.(dirty); }, [dirty, baseline.acked]);
  useEffect(() => () => report.current?.(false), []);
  const ta = useRef<HTMLTextAreaElement>(null), sb = useRef<HTMLButtonElement>(null), back = useRef(false);
  const q = useQuery({ queryKey: journalKey(c.record_id), queryFn: () => fetchJournal(c.record_id) });
  const off = locked || !quoteOk(q.data, c);
  // 열면 편집 칸으로, 취소로 닫으면 문장 버튼으로 포커스를 돌린다(닫힌 뒤에야 버튼이 다시 그려진다)
  useEffect(() => { if (open) ta.current?.focus(); else if (back.current) { back.current = false; sb.current?.focus(); } }, [open]);
  // 취소 = 초안을 버리고 최신 원격 문장, revision 을 기준으로
  const cancel = () => { back.current = true; setOpen(false); setText(c.text); setBaseline(b => ({ ...b, text: c.text, revision: c.revision })); };
  const decide = (action: string, t?: string) => {
    const sent = text;   // 저장을 누른 때의 문장 — edit_confirm 이 성공하면 이것이 새 기준(실패, 충돌, 다른 결정이면 기준 그대로, 고친 문장은 보호된다)
    onDecide(action, t, () => { if (action === "edit_confirm") setBaseline(b => ({ ...b, text: sent, acked: b.acked + 1 })); }, baseline.revision);
  };
  const id = c.id;
  return (
    <article className={css.item} id={"cand-" + id} tabIndex={-1} aria-labelledby={"ct-" + id}>
      <p id={"lead-" + id} className={css.lead} role="status" aria-atomic="true">{lead}</p>
      <section className={aiMark(c) ? `${css.card} ${css.ai}` : css.card} data-candidate-id={id}>
        <h3 id={"ct-" + id} className="sr">{w.cardTitle} {n}</h3>
        {open ? <p className={css.sent}>{c.text}</p>
          : <p className={css.sent}><button ref={sb} type="button" className={ed.hval} title="눌러서 고치기" aria-expanded={false} aria-controls={"rvedit-" + id}
            disabled={off} onClick={() => setOpen(true)}>{lastWord(c.text)}</button></p>}
        <Labels c={c} /><ReviewNote review={c.review} />
        <form id={"rvedit-" + id} className={css.edit} hidden={!open} aria-describedby={"edit-help-" + id}
          onKeyDown={e => { if (e.key === "Escape" && !locked) { e.preventDefault(); cancel(); } }}
          onSubmit={e => { e.preventDefault(); decide("edit_confirm", text); }}>
          <label htmlFor={"rvtext-" + id}>{w.editLabel}</label><p id={"edit-help-" + id} className="hint">{w.editHint} 원문은 바뀌지 않아요.</p>
          <textarea id={"rvtext-" + id} ref={ta} name="text" rows={3} required value={text} onChange={e => setText(e.target.value)} />
          <div className="acts"><button className="primary" type="submit" disabled={off}>고친 문장으로 남기기</button>
            <button className="tertiary" type="button" disabled={locked} onClick={cancel}>취소</button></div></form>
      </section>
      <Source S={S} c={c} j={q.data} fail={q.isError ? apiErr(q.error) : null} w={w} />
      <div className={css.act} aria-busy={locked}>
        {open ? null : <div className={`acts ${css.decide}`} role="group" aria-label={w.group} aria-describedby="decision-help">
          <button className="secondary" type="button" disabled={off} onClick={() => decide("confirm")}>{w.confirm}</button>
          <button className="secondary" type="button" disabled={off} onClick={() => decide("exclude")}>{w.exclude}</button></div>}
        <p id={"save-status-" + id} className={css.status} role="status" aria-atomic="true">{status}</p>
        <p id={"save-error-" + id} role="alert" aria-atomic="true" className="blocked">{err}</p>
      </div>
    </article>
  );
}
