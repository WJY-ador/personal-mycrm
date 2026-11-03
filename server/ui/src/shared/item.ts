// 항목 결정(/api/item/decide) · 휴지통 이동(/api/trash/move) — 「나」 상세와 구조 서랍이 같이 쓰는 서버 접점. 응답 정본 = server/web.py.
// 삭제 확인·결과 문구(r4 §8 글자 그대로)와 실패 문구(옛 trashErrText·coreFail 규칙)도 한 벌.
import { postJSON, type ApiError } from "./api";

export type ItemDecide = { item_id: string; expected_revision: number; action: string; proposal_id?: string };
export const itemDecide = <T = { deleted?: boolean }>(body: ItemDecide) => postJSON<T>("/api/item/decide", body);
export const trashMove = (kind: string, id: string, rev: number | null) =>
  postJSON("/api/trash/move", rev == null ? { kind, id } : { kind, id, expected_revision: rev });

export const TRASH_ASK = "삭제하면 휴지통으로 이동해요. 삭제 시각부터 168시간 동안 복원할 수 있고, 이후 서버 정리 때 영구 삭제돼요.";
export const TRASH_DONE = "휴지통으로 옮겼어요.";

const CORE: Record<string, string> = {
  CONFLICT: "다른 곳에서 먼저 바뀌었어요. 다시 불러왔어요 — 확인하고 다시 해 주세요.", "NOT-FOUND": "찾을 수 없어요. 지워졌을 수 있어요. 다시 불러왔어요.",
};
// 축 삭제가 장치 허용 규칙에 막힘 = 서버 문구(장치 이름 포함) 그대로
export function trashErr(e: ApiError) {
  if (e.code === "AXIS-IN-POLICY") return e.msg || "이 축을 쓰는 장치 허용 규칙이 있어 삭제할 수 없어요. 연결 장치에서 이 축을 뺀 뒤 다시 해 주세요.";
  if (e.code === "OFFLINE") return "서버에 연결하지 못했어요. 잠시 뒤 다시 해 보세요.";
  return CORE[e.code] || e.msg || "처리하지 못했어요. 다시 해 보세요.";
}
