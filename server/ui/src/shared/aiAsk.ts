// 웹 AI 대화에 정해진 요청을 넣어 여는 다리(구조 추천 받기, 2026-11-18) — features 끼리 import 하지 않으므로 shared 에 둔다.
// 웹 대화 섬(features/webchat/WebchatRoot)이 떠 있는 동안 받는 쪽 하나를 건다. 없으면(스위치 꺼짐) ask 는 false.
// 주소 표지(2026-11-18 대화 연결 상시) — 주소 hash 가 이것이면 웹 대화 패널을 연다(처음 열 때, hashchange 둘 다). 연 뒤 표지는 지운다.
// PC 앱이 AI 연결 링크(mycrm://connection?step=provider)를 받으면 대시보드를 이 표지로 연다. 라우터(layout/useHash)는 이 hash 를 화면 주소로 보지 않는다
export const AI_HASH = "#_ai";
export const hashOf = (url: string | undefined) => { try { return url ? new URL(url).hash : ""; } catch { return ""; } };
type Handler = (text: string) => void;
let handler: Handler | null = null;

export const aiAsk = {
  on(h: Handler) { handler = h; return () => { if (handler === h) handler = null; }; },
  ready: () => handler !== null,
  ask(text: string) { if (!handler) return false; handler(text); return true; },
};
