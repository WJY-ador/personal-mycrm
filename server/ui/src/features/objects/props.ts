import type { ReactNode } from "react";
import type { UiCtx } from "../../shared/ctx";
import type { AppState } from "../../shared/state";

// 화면 조각 공통 — ctx(다시 받기) · S(껍데기 상태) · msg(결과 한 줄 #core-msg — 위치 줄 아래)
export type P = { ctx: UiCtx; S: AppState; msg: ReactNode };
