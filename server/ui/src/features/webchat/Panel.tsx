// 패널 — 머리글(PC 연결 상태 · 닫기) · 메시지 목록 · 상태 한 줄 · 입력 칸(보내기 · 중지 · 8,000자 카운터). ⌘/Ctrl+Enter = 보내기 · Esc = 닫기.
import { useEffect, useRef, type RefObject } from "react";
import type { WebchatStore } from "./store";
import { TurnView } from "./TurnView";
import { EMPTY, KEEP, PC_OFF, PC_ON, TEXT_MAX, TITLE } from "./text";
import css from "./Webchat.module.css";

export function Panel({ s, inRef }: { s: WebchatStore; inRef: RefObject<HTMLTextAreaElement | null> }) {
  const n = [...s.input].length, end = useRef<HTMLDivElement>(null);
  const last = s.turns[s.turns.length - 1];
  useEffect(() => { end.current?.scrollIntoView?.({ block: "end" }); }, [s.turns.length, last?.answer, last?.tools.length]);
  return (
    <aside className={css.panel} id="webchat" hidden={!s.open} aria-label={TITLE}
      onKeyDown={e => { if (e.key === "Escape") void s.toggle(false); }}>
      <header className={css.head}><h3>{TITLE}</h3>
        <span className={`${css.pc}${s.connected ? ` ${css.up}` : ""}`} role="status">{s.sid ? (s.connected ? PC_ON : PC_OFF) : ""}</span>
        <button type="button" className="tertiary" onClick={() => void s.toggle(false)}>닫기</button></header>
      <div className={css.body}>
        {s.trimmed && <p className={css.empty}>{s.trimmed}</p>}
        {s.turns.length ? s.turns.map(t => <TurnView key={t.id} t={t} />) : <p className={css.empty}>{EMPTY}</p>}
        <div ref={end} />
      </div>
      <p className={`${css.line}${s.bad ? ` ${css.bad}` : ""}`} role="status" aria-live="polite">{s.line || KEEP}</p>
      <form className={css.comp} onSubmit={e => { e.preventDefault(); void s.send(); }}>
        <textarea ref={inRef} rows={3} placeholder="무엇이든 말해 보세요" aria-label="대화 입력" value={s.input}
          onChange={e => { s.input = e.target.value; s.emit(); }}
          onKeyDown={e => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); void s.send(); } }} />
        <div className={css.row}>
          <span className={`${css.count}${n > TEXT_MAX ? ` ${css.bad}` : ""}`}>{`${n.toLocaleString()} / ${TEXT_MAX.toLocaleString()}`}</span>
          {s.running() && <button type="button" className="secondary" onClick={() => void s.stop()}>중지</button>}
          <button type="submit" className="primary" disabled={!s.canSend()}>보내기</button></div>
      </form>
    </aside>
  );
}
