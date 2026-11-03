// 판단 검토 문구(옛 app.html renderReview·decide 글자 그대로). 판단 검토는 옛 탐색(nav=old)에서도 열린다 — 새 탐색 말 / 옛 말 두 벌(옛 TX).
// 옛 쪽에 같은 문구가 남은 것(CONFLICT_TEXT·FIXHINT·WHAT·칩 origin·decision)은 다른 옛 화면이 쓰는 일시 중복 — R5 에서 한쪽만(migrated.json temp_duplicates).
export const CONFLICT_TEXT = "다른 곳에서 먼저 바뀌었어요. 새로 고침해 다시 봐 주세요.";
export const FIXHINT = "새로 고침해도 그대로면 다시 로그인해 보세요.";
export const NO_QUESTION = "질문 없음";

export function words(oldNav: boolean) {
  const TX = (n: string, o: string) => (oldNav ? o : n);
  return {
    record: TX("내 글", "기록"), mine: TX("확정한 판단", "내 판단"),
    recGone: TX("찾을 수 없는 글", "찾을 수 없는 기록"), recMissing: TX("글이 지워졌거나 찾을 수 없어요.", "기록이 지워졌거나 찾을 수 없어요."),
    emptyHint: TX("새 글에서 판단을 뽑으면 여기에 떠요.", "새 기록에서 후보를 뽑으면 여기에 떠요."),
    cardTitle: TX("검토할 판단", "판단 후보"),
    keepNote: TX("반영 안 함으로 둬도 판단 문장과 원문은 삭제되지 않아요.", "반영 안 함으로 둬도 후보와 원문은 삭제되지 않아요."),
    group: TX("판단 결정", "후보 결정"), confirm: TX("남기기", "내 판단으로 남기기"),
    editLabel: TX("확정한 판단으로 남길 문장", "내 판단으로 남길 문장"), editHint: TX("판단 문장을 고쳐요.", "후보 문장을 고쳐요."),
    navLabel: TX("판단 이동", "후보 이동"),
    mismatch: TX("이 판단의 근거 구절이 저장된 원문과 일치하지 않아 남길 수 없어요.", "후보의 근거 구절이 저장된 원문과 일치하지 않아 남길 수 없어요."),
    oldMark: TX("쓸 당시 표기", "기록 당시 표기"), attach: TX("이 글이 붙는 곳", "이 기록이 붙는 곳"),
    saved: (a: string) => (oldNav
      ? { confirm: "내 판단으로 남겼어요.", edit_confirm: "고친 문장을 내 판단으로 남겼어요.", exclude: "반영 안 함으로 표시했어요." }
      : { confirm: "확정한 판단으로 남겼어요.", edit_confirm: "고친 문장을 확정한 판단으로 남겼어요.", exclude: "반영 안 함으로 표시했어요." })[a] || "",
  };
}
export type Words = ReturnType<typeof words>;

// 「…으로/로 돌아가기」 조사는 껍데기가 고른다(돌아갈 곳 = 껍데기 라우터의 lastView) — 이 화면은 받은 글자를 그대로 쓴다
export const SAVING = "저장하고 있어요…";
export const CHECKING = "저장 결과를 확인하고 있어요…";
export const UNKNOWN = "저장 여부를 확인하지 못했어요. 새로 고침해 확인해 주세요.";
export const SAVE_FAIL = "저장하지 못했어요. 다시 시도해 주세요.";
export const unsavedEdit = (t: string) => ` 고치던 문장은 저장되지 않았어요: 「${t}」`;
