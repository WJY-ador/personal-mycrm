// 판단 검토 문구(옛 app.html renderReview·decide 글자 그대로).
// 충돌 문구·칩·못 읽음 표시는 shared(postErr·CandChips·PartFail) 한 벌.
export { CONFLICT_TEXT } from "../../shared/postErr";
export { FIXHINT } from "../../shared/Tech";
export { NO_QUESTION } from "../../shared/clip";

const SAVED: Record<string, string> = { confirm: "확정한 판단으로 남겼어요.", edit_confirm: "고친 문장을 확정한 판단으로 남겼어요.", exclude: "반영 안 함으로 표시했어요." };
export const WORDS = {
  record: "내 글", mine: "확정한 판단",
  recGone: "찾을 수 없는 글", recMissing: "글이 지워졌거나 찾을 수 없어요.",
  emptyHint: "새 글에서 판단을 뽑으면 여기에 떠요.",
  cardTitle: "검토할 판단",
  keepNote: "반영 안 함으로 둬도 판단 문장과 원문은 삭제되지 않아요.",
  group: "판단 결정", confirm: "남기기",
  editLabel: "확정한 판단으로 남길 문장", editHint: "판단 문장을 고쳐요.",
  navLabel: "판단 이동",
  mismatch: "이 판단의 근거 구절이 저장된 원문과 일치하지 않아 남길 수 없어요.",
  oldMark: "쓸 당시 표기",
  saved: (a: string) => SAVED[a] || "",
};
export type Words = typeof WORDS;

// 「…으로/로 돌아가기」 조사는 껍데기가 고른다(돌아갈 곳 = 껍데기 라우터의 lastView) — 이 화면은 받은 글자를 그대로 쓴다
export const SAVING = "저장하고 있어요…";
export const CHECKING = "저장 결과를 확인하고 있어요…";
export const UNKNOWN = "저장 여부를 확인하지 못했어요. 새로 고침해 확인해 주세요.";
export const SAVE_FAIL = "저장하지 못했어요. 다시 시도해 주세요.";
export const unsavedEdit = (t: string) => ` 고치던 문장은 저장되지 않았어요: ${t}`;
