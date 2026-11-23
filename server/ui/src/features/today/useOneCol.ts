// 수집 인박스 한 칸 여부 — 두 칸(목록 | 읽기 판)과 한 칸(줄 아래 펼침)의 문턱. 정본 shared/breakpoints.ts BP.board(900).
// Collected.module.css 의 @media (max-width: 900px) 와 같은 값이라, 화면 모양과 줄을 눌렀을 때의 동작이 같은 기준으로 바뀐다.
import { useSyncExternalStore } from "react";
import { BP, maxW } from "../../shared/breakpoints";

const mq = () => window.matchMedia(maxW(BP.board));
export const useOneCol = () => useSyncExternalStore(cb => { const m = mq(); m.addEventListener("change", cb); return () => m.removeEventListener("change", cb); }, () => mq().matches);
