// 입력 칸 하나 — 글상자 + 한 줄(모델 고르기 · 글자 수 · 중지 · 보내기). 새 대화의 첫 메시지를 보내면 고른 모델로 대화가 시작된다.
// PC 허용을 기다리는 동안은 글상자를 잠근다(보내려던 글은 그대로 두고, 허용되면 그 글을 보낸다).
// J-F4(JD4): Enter = 보내기, Shift+Enter = 줄바꿈. 한글 조합 중 Enter(isComposing, keyCode 229)는 글자 확정이라 보내지 않는다.
// 보내기가 막힌 때(진행 중, 허용 대기 중)의 Enter 는 store.send 가 무시한다(J-F3: 같은 요청을 다시 보내지 않는다).
import type { RefObject } from "react";
import { sendKey } from "./keys";
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
        onKeyDown={e => { if (sendKey(e)) { e.preventDefault(); void s.send(); } }} />
      <div className={css.row}>
        <ModelPicker s={s} dev={dev} />
        <span className={`${css.count}${n > TEXT_MAX ? ` ${css.bad}` : ""}`}>{`${n.toLocaleString()} / ${TEXT_MAX.toLocaleString()}`}</span>
        {s.running() && <button type="button" className="secondary" onClick={() => void s.stop()}>중지</button>}
        <button type="submit" className="primary" disabled={!s.canSend()}>보내기</button></div>
    </form>
  );
}
