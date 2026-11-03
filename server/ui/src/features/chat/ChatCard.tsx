// 확인 카드 — 정리 글(고치면 즉시 [확정] 잠금 · 칸을 벗어나면 재정리) · 바뀌는 것(기본 포함, 끄기 = 예외 제외) · 뺀 것(되돌릴 수 없어 체크 칸 없음)
// · 정해 주세요(답 + Enter = 재정리) · [확정] 하나. 장치 없음 = 재정리를 부르는 칸 잠금(정리 글 읽기만·막힘 답 잠금), 끄기·확정은 된다.
import { useRef } from "react";
import type { ChatStore } from "./store";
import { blocking, changes, included, isGuess, label, off } from "./store";
import { cp } from "./text";
import type { Preview } from "./types";
import css from "./Chat.module.css";

export function ChatCard({ s, p }: { s: ChatStore; p: Preview }) {
  const unitsRef = useRef<HTMLDivElement>(null);
  const inf = new Set(changes(p).filter(isGuess).map(c => c.cid)), o = off(p), blk = blocking(p), inc = included(p), nodev = s.noDev();
  // 뺀 것 이름 = 서버 excluded_changes[].summary(첫 판의 표시 요약) → 없으면 같은 결과에서 본 변경 → 그래도 없으면 「앞서 뺀 변경」
  const xname = new Map((p.excluded_changes || []).map(x => [x.cid, x.summary]));
  return (
    <section className={css.card} id="chat-card" aria-label="확인">
      <p className={css.lead}>이렇게 정리했어요. 맞나요? 고칠 곳은 바로 고치세요 — 고친 글은 다시 정리해요.</p>
      <div className={css.units} ref={unitsRef}>{(p.units || []).map(u => (
        <div className={css.unit} key={u.uid}>
          <textarea data-uid={u.uid} rows={Math.min(8, Math.max(2, Math.ceil(cp(u.text) / 34)))} aria-label="정리 글" readOnly={nodev}
            value={s.edits[u.uid] ?? u.text} onChange={e => s.edit(u.uid, e.target.value)}
            onBlur={e => { if (!(e.relatedTarget && unitsRef.current?.contains(e.relatedTarget))) s.leave(); }} />
          {(u.change_ids || []).some(c => inf.has(c)) && <span className="chip o-ai" title="문맥으로 고른 대상이에요. 맞지 않으면 아래에서 끄거나 글을 고치세요.">추정</span>}
        </div>))}</div>
      {inc.length > 0 && <><h4>바뀌는 것 {inc.length}</h4><ul className={css.chg}>{inc.map(c => (
        <li key={c.cid}><label><input type="checkbox" data-cid={c.cid} checked={!s.unchecked.has(c.cid)} disabled={!s.canToggle()}
          onChange={e => { if (!e.target.checked) void s.exclude(c.cid); }} /><span>{label(c)}</span></label>
          {isGuess(c) && <span className="chip o-ai">추정</span>}</li>))}</ul></>}
      {o.size > 0 && <><h4>뺀 것 {o.size}</h4><ul className={css.chg}>{[...o].map(cid => (
        <li key={cid} className={css.out} data-xcid={cid}><span>{xname.get(cid) || s.known[cid] || "앞서 뺀 변경"}</span><span className={css.cnote}>뺐어요</span></li>))}</ul></>}
      {blk.length > 0 && <><h4>정해 주세요 {blk.length}</h4>{blk.map((b, i) => (
        <div className={css.blk} key={i}><p>{b.question || "이 부분을 정하지 못했어요."}</p>
          <input type="text" data-bq={b.cid || ""} placeholder="답을 적고 Enter" aria-label="답" disabled={nodev} value={s.answers[i] || ""}
            onChange={e => s.setAnswer(i, e.target.value)}
            onKeyDown={e => { if (e.key === "Enter" && !e.nativeEvent.isComposing) { e.preventDefault(); s.answer(); } }} /></div>))}</>}
      <div className={css.acts}><button type="button" className="primary" id="chat-confirm" disabled={!s.canConfirm()} onClick={() => void s.confirm()}>확정</button></div>
    </section>
  );
}
