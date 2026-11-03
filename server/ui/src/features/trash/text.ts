// 휴지통 화면 문구(r4 §8 글자 그대로). 「영구 삭제 처리 중·예정」 같은 화면 상태는 두지 않는다.
import type { ApiError } from "../../shared/api";

export const TRASH_KIND: Record<string, string> = {
  record: "내 글", item: "항목", activity: "활동", person: "사람", reflection: "읽고 든 생각",
};
export const TRASH_NOTE = "복원 기한이 지나면 목록에서 사라지고 복원할 수 없어요. 본문은 이후 서버 정리 때 삭제돼요.";
export const TRASH_PURGE_ASK = "지금부터 복원할 수 없어요. 본문은 서버 정리 때 영구 삭제돼요.";
export const TRASH_PURGED = "영구 삭제를 요청했어요. 이제 복원할 수 없어요.";
export const TRASH_RESTORED = "복원했어요.";
export const TRASH_EMPTY = "휴지통이 비어 있어요.";
export { LOADING } from "../../shared/words";
export const MORE_FAIL = "더 불러오지 못했어요. 다시 눌러 주세요.";

export const loadErrText = (e: ApiError) =>
  e.code === "OFFLINE" ? "서버에 연결하지 못했어요." : "휴지통을 불러오지 못했어요. 새로 고침해 주세요.";

// 복원·영구 삭제 실패 — 옛 corePost + trashErrText 와 같은 결과 문장
export function actErrText(e: ApiError): string {
  if (e.code === "OFFLINE") return "서버에 연결하지 못했어요. 잠시 뒤 다시 해 보세요.";
  if (e.code === "TRASH-EXPIRED") return "복원 기간이 끝났어요.";
  if (e.code === "CONFLICT") return "다른 곳에서 먼저 바뀌었어요. 다시 불러왔어요 — 확인하고 다시 해 주세요.";
  if (e.code === "NOT-FOUND") return "찾을 수 없어요. 지워졌을 수 있어요. 다시 불러왔어요.";
  return e.msg || "저장하지 못했어요. 다시 해 보세요.";
}
