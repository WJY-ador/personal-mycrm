// 서랍 — 머리글(장치 상태 · 임시 보관 시각) · 닫기 · 대화 턴 · 확인 카드 · 상태 한 줄 · 입력 칸(보내기 · 원문으로 저장 · 8,000자 카운터).
// 장치 없음 = 입력 칸 대신 안내 1줄 · PC 오프라인 = 입력 칸은 두고 할 일 안내 1줄(보낸 글은 PC 가 오면 이어서 정리). 원문으로 저장 = 세션 첫 입력만. ⌘/Ctrl+Enter = 보내기 · Esc(고치는 중이 아닐 때) = 닫기.
import type { RefObject } from "react";
import { Sprout } from "../../shared/Sprout";
import type { ChatStore } from "./store";
import { ChatCard } from "./ChatCard";
import { CHAT_MAX, CHAT_NODEV, CHAT_OFFLINE, EMPTY_TURNS, cp } from "./text";
import css from "./Chat.module.css";

export function ChatDrawer({ s, inRef }: { s: ChatStore; inRef: RefObject<HTMLTextAreaElement | null> }) {
  const nodev = s.noDev(), n = cp(s.input), note = nodev ? CHAT_NODEV : s.offline() ? CHAT_OFFLINE : "";
  const working = !!(s.busy || s.polling) && !s.offline();   // 기다림 캐릭터 = 장식(상태 줄 글자가 따로 읽힌다). 오프라인 대기는 진행 중으로 보이지 않게(store 115줄과 같은 이유)
  return (
    <aside className={css.chat} id="chat" hidden={!s.open} aria-label="대화"
      onKeyDown={e => { if (e.key === "Escape" && s.open && !s.dirty) s.toggle(false); }}>
      <header className={css.head}><h3>대화</h3><span className={css.ctx}>{s.ctxText()}</span>
        <button type="button" className="tertiary" onClick={() => s.toggle(false)}>닫기</button></header>
      <div className={css.body}>
        <div className={css.turns}>{s.turns.length ? s.turns.map((t, i) => <p className={css.turn} key={i}>{t}</p>)
          : !s.preview && <p className={css.empty}>{EMPTY_TURNS}</p>}</div>
        {s.card && <ChatCard key={`${s.card.id}:${s.card.preview_version}`} s={s} p={s.card} />}
      </div>
      <p className={`${css.line}${s.bad ? ` ${css.bad}` : ""}`} role="status" aria-live="polite">{working && <Sprout />}{working && " "}{s.line}</p>
      <p className={css.line} role="note" hidden={!note}>{note}</p>
      <form className={css.comp} hidden={nodev} onSubmit={e => { e.preventDefault(); void s.send(); }}>
        <textarea ref={inRef} rows={3} placeholder="말하거나 원문을 붙여 넣으세요" aria-label="대화 입력" value={s.input}
          onChange={e => { s.input = e.target.value; s.emit(); }}
          onKeyDown={e => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); void s.send(); } }} />
        <div className={css.row}>
          <label hidden={!!s.sid}><input type="checkbox" checked={s.verbatim} onChange={e => { s.verbatim = e.target.checked; s.emit(); }} /> 원문으로 저장</label>
          <span className={`${css.count}${n > CHAT_MAX ? ` ${css.bad}` : ""}`}>{`${n.toLocaleString()} / ${CHAT_MAX.toLocaleString()}`}</span>
          <button type="submit" className="primary" disabled={!s.canSend()}>보내기</button></div>
      </form>
    </aside>
  );
}
