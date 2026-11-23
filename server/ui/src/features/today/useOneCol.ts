// 수집 인박스 한 칸 여부 — 두 칸(목록 | 읽기 판)과 한 칸(줄 아래 펼침)의 문턱. 정본 shared/breakpoints.ts BP.board(900).
// Collected.module.css 의 @media (max-width: 900px) 와 같은 값이라, 화면 모양과 줄을 눌렀을 때의 동작이 같은 기준으로 바뀐다.
// useTouch(16-1) — 주 포인터가 터치인 기기(가로 태블릿 등). HTML 끌어 놓기가 안 돼 두 칸에서도 줄 누름으로 읽기 판에 띄운다.
import { useSyncExternalStore } from "react";
import { BP, maxW } from "../../shared/breakpoints";

const useMq = (q: string) => useSyncExternalStore(cb => { const m = window.matchMedia(q); m.addEventListener("change", cb); return () => m.removeEventListener("change", cb); },
  () => window.matchMedia(q).matches);
export const useOneCol = () => useMq(maxW(BP.board));
export const TOUCH_Q = "(hover: none) and (pointer: coarse)";
export const useTouch = () => useMq(TOUCH_Q);
