// 웹 AI 대화에 정해진 요청을 넣어 여는 다리(구조 추천 받기, 2026-11-18) — features 끼리 import 하지 않으므로 shared 에 둔다.
// 웹 대화 섬(features/webchat/WebchatRoot)이 떠 있는 동안 받는 쪽 하나를 건다. 없으면(스위치 꺼짐) ask 는 false.
type Handler = (text: string) => void;
let handler: Handler | null = null;

export const aiAsk = {
  on(h: Handler) { handler = h; return () => { if (handler === h) handler = null; }; },
  ready: () => handler !== null,
  ask(text: string) { if (!handler) return false; handler(text); return true; },
};
