// 1열(좁은 폭) 여부 — 미디어 질의(768 미만 = CSS 좁은 화면 분기점, 정본 shared/breakpoints.ts BP.narrow). 「나」·「오늘」이 같이 쓴다.
// MOBILE 은 글자 그대로 둔다(server/test_web_home.py 가 이 줄을 본다). 같은 값인지는 arch.test.ts 가 본다.
import { useSyncExternalStore } from "react";

export const MOBILE = "(max-width: 767px)";
const mq = () => window.matchMedia(MOBILE);
export const useMobile = () => useSyncExternalStore(cb => { const m = mq(); m.addEventListener("change", cb); return () => m.removeEventListener("change", cb); }, () => mq().matches);
