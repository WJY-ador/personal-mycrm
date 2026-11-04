// 웹 「대화」(구독 AI 채팅) 상시 섬 — 스위치 S.switches.webchat 켜짐일 때만 껍데기가 띄운다(layout/App). 옛 1턴 「대화」(features/chat)와 따로.
// 탭 줄 「AI 대화」 버튼은 #ui-chatnav 에 포털로, 패널은 오른쪽 고정(넓은 화면)·화면 전체(좁은 화면).
import { useEffect, useRef, useSyncExternalStore } from "react";
import { createPortal } from "react-dom";
import type { ScreenProps } from "../../shared/ctx";
import { Panel } from "./Panel";
import { webchat, type WebchatStore } from "./store";
import { TITLE } from "./text";
import css from "./Webchat.module.css";

export function WebchatRoot({ ctx, store = webchat }: ScreenProps & { store?: WebchatStore }) {
  const s = store;
  useSyncExternalStore(s.subscribe, s.version);
  const inRef = useRef<HTMLTextAreaElement>(null);
  const on = !!ctx.state?.switches?.webchat;
  useEffect(() => { document.body.classList.toggle("webchat-open", on && s.open); }, [on, s.open]);
  useEffect(() => () => { document.body.classList.remove("webchat-open"); s.close(); }, [s]);
  useEffect(() => { if (s.open) inRef.current?.focus(); }, [s.open]);
  if (!on) return null;
  const nav = document.getElementById("ui-chatnav");
  const btn = <a href="#" className={`tab ${css.btn}${s.open ? ` ${css.on} on` : ""}`} role="button" aria-pressed={s.open} aria-controls="webchat"
    onClick={e => { e.preventDefault(); void s.toggle(); }}>{TITLE}</a>;
  return (
    <>
      {nav && createPortal(btn, nav)}
      <Panel s={s} inRef={inRef} />
    </>
  );
}
