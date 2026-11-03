// 대화 서랍 상시 섬 — 껍데기가 새 상태(S)마다 #ui-chat 에 다시 띄운다(같은 자리 = 대화 유지). 스위치 S.switches.converse 켜짐 + 새 탐색일 때만.
// 탭 줄 「대화」 버튼(장치 없음 = 그 자리에 안내 1줄)은 #ui-chatnav, 좁은 화면 안내는 #ui-chatnote — 껍데기 고정 자리에 포털로 그린다.
import { useEffect, useRef, useSyncExternalStore } from "react";
import { createPortal } from "react-dom";
import type { ScreenProps } from "../../shared/ctx";
import { ChatDrawer } from "./ChatDrawer";
import { chat, type ChatStore } from "./store";
import { CHAT_NODEV } from "./text";
import css from "./Chat.module.css";

export function ChatRoot({ ctx, store = chat }: ScreenProps & { store?: ChatStore }) {
  const s = store;
  useSyncExternalStore(s.subscribe, s.version);
  const inRef = useRef<HTMLTextAreaElement>(null), focus = useRef(false);   // 버튼으로 열면 그린 뒤 입력 칸으로
  useEffect(() => { if (ctx.state) s.sync(ctx.state, ctx.reload); }, [s, ctx.state, ctx.reload]);
  useEffect(() => { document.body.classList.toggle("chat-open", s.open); }, [s.open]);
  useEffect(() => () => document.body.classList.remove("chat-open"), []);
  useEffect(() => { if (focus.current && s.open) inRef.current?.focus(); focus.current = false; });
  const shown = s.on() && s.navNew(), note = shown && s.noDev() && !s.curSid();   // 장치 없음 = 새 대화 버튼 대신 안내(죽은 버튼 0). 세션이 남았으면 버튼
  const nav = document.getElementById("ui-chatnav"), noteM = document.getElementById("ui-chatnote");
  const toggle = <a href="#" className={`tab ${css.btn}${s.open ? ` ${css.on} on` : ""}`} role="button" aria-pressed={s.open} aria-controls="chat"
    onClick={e => { e.preventDefault(); s.toggle(); focus.current = s.open; }}>대화</a>;
  return (
    <>
      {nav && shown && createPortal(note ? <span className={css.note} role="note">{CHAT_NODEV}</span> : toggle, nav)}
      {noteM && note && createPortal(<p className={`wrap ${css.noteM}`} role="note">{CHAT_NODEV}</p>, noteM)}
      {shown && <ChatDrawer s={s} inRef={inRef} />}
    </>
  );
}
