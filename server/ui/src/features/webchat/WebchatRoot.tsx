// 웹 「대화」(구독 AI 채팅) 상시 섬 — 스위치 S.switches.webchat 켜짐일 때만 껍데기가 띄운다(layout/App). 옛 1턴 「대화」(features/chat)와 따로.
// 탭 줄 AI 버튼(AI 하나로 A1, 탭 줄의 대화 버튼은 이것 하나)은 #ui-chatnav 에 포털로, 패널은 오른쪽 고정(넓은 화면)·화면 전체(좁은 화면).
import { useEffect, useRef, useSyncExternalStore } from "react";
import { createPortal } from "react-dom";
import { AI_HASH, aiAsk, hashOf } from "../../shared/aiAsk";
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
  useEffect(() => {   // R-J3: 창 focus, 탭이 다시 보일 때 capabilities 다시 읽기(묶기, 열린 패널 조건은 store)
    if (!on) return;
    const back = () => { if (document.visibilityState !== "hidden") s.refreshCapabilities(); };
    window.addEventListener("focus", back);
    document.addEventListener("visibilitychange", back);
    return () => { window.removeEventListener("focus", back); document.removeEventListener("visibilitychange", back); };
  }, [on, s]);
  useEffect(() => {   // 구조 추천 받기(2026-11-18) — 정해진 요청을 입력칸에 채워 연다. 보내기는 사용자가 누른다. 쓰던 글이 있으면 덮지 않는다
    if (!on) return;
    return aiAsk.on(text => { if (!s.input.trim()) { s.input = text; s.emit(); } void s.toggle(true); });
  }, [on, s]);
  useEffect(() => {   // 주소 표지 #_ai(2026-11-18) — 처음 열 때와 hashchange 에 패널을 연다. 표지는 replaceState 로 지운다(뒤로 가기 기록을 늘리지 않음).
    if (!on) return;   // hashchange 로 왔으면 앞 주소(oldURL 의 hash)로 되돌려 보던 화면을 그대로 둔다. 이미 열려 있으면 그대로
    const take = (back = "") => {
      if (location.hash !== AI_HASH) return;
      history.replaceState(history.state, "", location.pathname + location.search + (back === AI_HASH ? "" : back));
      if (!s.open) void s.toggle(true);
    };
    take();
    const f = (e: HashChangeEvent) => take(hashOf(e.oldURL));
    window.addEventListener("hashchange", f);
    return () => window.removeEventListener("hashchange", f);
  }, [on, s]);
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
