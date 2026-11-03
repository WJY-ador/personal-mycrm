// 옛 corePost·coreFail 실패 규칙 — 화면이 문구를 짓지 않는다(연결 실패·충돌·없음만 화면 문구, 그 밖은 서버 msg).
// RELOAD = 상태를 다시 받아야 하는 실패(그 화면 머리에 문구 + ctx.reload). 연결 장치·이관이 쓴다.
import type { ApiError } from "./api";

const CORE_ERR: Record<string, string> = {
  CONFLICT: "다른 곳에서 먼저 바뀌었어요. 다시 불러왔어요 — 확인하고 다시 해 주세요.",
  "NOT-FOUND": "찾을 수 없어요. 지워졌을 수 있어요. 다시 불러왔어요.",
};
export const RELOAD = new Set(["CONFLICT", "NOT-FOUND", "NAME-REQUIRED"]);

export const postMsg = (e: ApiError) =>
  e.code === "OFFLINE" ? "서버에 연결하지 못했어요. 잠시 뒤 다시 해 보세요." : CORE_ERR[e.code] || e.msg || "저장하지 못했어요. 다시 해 보세요.";
