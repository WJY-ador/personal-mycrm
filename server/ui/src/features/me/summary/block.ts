// 요약 블록 계약 — 레지스트리(server/layout_registry.json components)의 id 하나 = 블록 컴포넌트 하나(src/layout/registry.ts 가 묶는다).
// p = 슬롯 props(레이아웃 저장값 그대로) · W = 화면이 가진 것 · statsFail = 통계를 못 받음(숫자는 서버 /api/me/stats 그대로 — 화면에서 다시 세지 않는다)
import type { ComponentType } from "react";
import type { World } from "../model";

export type BlockProps = { p: Record<string, unknown>; W: World; statsFail: boolean };
export type Blocks = Record<string, ComponentType<BlockProps>>;
export const today = () => new Date().toLocaleDateString("sv-SE", { timeZone: "Asia/Seoul" });   // YYYY-MM-DD(KST)
