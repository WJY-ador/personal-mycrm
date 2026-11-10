// 입력 칸 하나 — 글상자 + 한 줄(모델 고르기 · 글자 수 · 중지 · 보내기). 새 대화의 첫 메시지를 보내면 고른 모델로 대화가 시작된다.
// PC 허용을 기다리는 동안은 글상자를 잠근다(보내려던 글은 그대로 두고, 허용되면 그 글을 보낸다).
import type { RefObject } from "react";
import { ModelPicker } from "./ModelPicker";
import type { WebchatStore } from "./store";
import { PLACEHOLDER, TEXT_MAX } from "./text";
import css from "./Webchat.module.css";

export function Composer({ s, inRef, dev }: { s: WebchatStore; inRef: RefObject<HTMLTextAreaElement | null>; dev: string }) {
  const n = [...s.input].length;
  return (
    <form className={css.comp} onSubmit={e => { e.preventDefault(); void s.send(); }}>
      <textarea ref={inRef} rows={2} disabled={s.loading || s.waiting()} placeholder={PLACEHOLDER} aria-label="대화 입력" value={s.input}
        onChange={e => { s.input = e.target.value; s.emit(); }}
        onKeyDown={e => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); void s.send(); } }} />
      <div className={css.row}>
        <ModelPicker s={s} dev={dev} />
        <span className={`${css.count}${n > TEXT_MAX ? ` ${css.bad}` : ""}`}>{`${n.toLocaleString()} / ${TEXT_MAX.toLocaleString()}`}</span>
        {s.running() && <button type="button" className="secondary" onClick={() => void s.stop()}>중지</button>}
        <button type="submit" className="primary" disabled={!s.canSend()}>보내기</button></div>
    </form>
  );
}
