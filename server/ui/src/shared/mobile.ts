// 1열(좁은 폭) 여부 — 미디어 질의(768 미만 = app.html CSS 분기점·HOME_MOBILE 과 같은 값). 「나」·「오늘」이 같이 쓴다.
import { useSyncExternalStore } from "react";

export const MOBILE = "(max-width: 767px)";
const mq = () => window.matchMedia(MOBILE);
export const useMobile = () => useSyncExternalStore(cb => { const m = mq(); m.addEventListener("change", cb); return () => m.removeEventListener("change", cb); }, () => mq().matches);
