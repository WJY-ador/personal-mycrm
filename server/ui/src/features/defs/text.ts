// 내 구조 설정 문구(옛 app.html 구조 정의·편입 미리보기 절 글자 그대로). 잠금 영향 코드 = 서버 contract.LOCKED_CHANGES, 충돌·불가 사유 = db._std_assess.
// 정의를 바꾸는 일은 연결한 AI 대화에서 — 이 화면의 쓰기는 표준 편입 선택(보류·거절·편입)과 구조 이름 공유 동의뿐이다.
export const LOCK_TIP = "편입된 표준 정의예요. key·종류·표준 필드 모양은 바꿀 수 없고, label 은 바꿀 수 있어요.";
export const VTYPE: Record<string, string> = { text: "글", number: "숫자", boolean: "예/아니오", date: "날짜", select: "고르기", text_list: "글 목록", reference: "참조" };
export const KIND_LABEL: Record<string, string> = { principle: "기준", event: "결정", collection: "모음" };
export const CORE_LABEL: Record<string, string> = { record: "내 글", candidate: "검토할 판단" };
export const STD_STATE: Record<string, [string, string]> = { seeded: ["st-mine", "처음부터 표준"], incorporated: ["st-mine", "편입함"], deferred: ["st-wait", "보류"],
  refused: ["st-off", "거절"], none: ["", "아직 고르지 않음"] };
export const STD_READY = ["seeded", "incorporated"];
export const STRUCT_TEXT: Record<string, string> = { match: "일치 — 표준과 같은 모양", extend: "확장 — 표준 + 내가 더한 필드", missing: "누락 — 같은 key 자료 종류가 없어요",
  conflict: "충돌 — 표준과 모양이 달라요" };
export const STD_CONFLICT: Record<string, (f: string) => string> = {
  key_draft_only: () => "같은 key 자료 종류가 아직 적용 전 초안이에요. 대화에서 초안을 적용하거나 key 를 바꾼 뒤 다시 보세요",
  key_archived: () => "같은 key 자료 종류가 보관돼 있어요",
  kind: () => "자료 종류의 의미 유형(semantic_kind)가 표준과 달라요",
  field_missing: f => `표준 필드 ${f} 가 없어요`,
  field_archived: f => `표준 필드 ${f} 가 보관돼 있어요`,
  field_value_type: f => `필드 ${f} 의 값 종류가 표준과 달라요`,
  field_target_kind: f => `필드 ${f} 가 가리키는 종류가 표준과 달라요`,
  field_target: f => `필드 ${f} 가 표준 대상 자료 종류를 가리키지 않아요`,
  field_multiple: f => `필드 ${f} 의 여러 개 허용이 표준과 달라요`,
  field_required: f => `필드 ${f} 의 필수 여부가 표준과 달라요`,
  field_options: f => `필드 ${f} 에 표준 선택지가 빠져 있어요`,
};
export const BLOCK_TEXT: Record<string, string> = { already: "이미 표준으로 쓰고 있어요.", conflict: "구조가 표준과 달라요. 대화로 정의를 표준 모양에 맞춘 뒤 다시 보세요.",
  needs_target: "참조 대상 표준을 먼저 편입해야 해요." };
// 편입하면 막히는 변경 — 서버 contract.LOCKED_CHANGES 코드와 같은 뜻
export const LOCK_TEXT: Record<string, string> = { archive: "자료 종류 삭제·보관", key: "자료 종류 key 바꾸기", semantic_kind: "자료 종류의 의미 유형(semantic_kind) 바꾸기",
  std_id: "표준 식별자 떼기·바꾸기 — 보류·거절로 되돌리기 포함", field_remove: "표준 필드 빼기",
  field_shape: "표준 필드의 key·값 종류·대상·여러 개·필수 바꾸기", option_remove: "표준 선택지 빼기·값 바꾸기" };
export const STD_DONE: Record<string, string> = { deferred: "보류로 남겼어요. 다른 기능은 그대로예요.", refused: "거절로 남겼어요. 기존 자료 종류와 링크는 그대로예요.",
  incorporated: "편입했어요. 이 정의는 이제 「표준 정의 보호」를 받아요." };
export const STD_ERR: Record<string, string> = {
  "DEF-INVALID": "지금 구조로는 편입할 수 없어요. 미리보기를 다시 불러왔어요 — 사유를 확인해 주세요.",
  "CONFLICT": "다른 곳에서 먼저 바뀌었어요. 미리보기를 다시 불러왔어요 — 다시 확인해 주세요.",
  "STANDARD-LOCKED": "이미 편입된 표준은 보류·거절로 바꿀 수 없어요.",
};
export { FIXHINT } from "../../shared/Tech";
export { josa, roJosa } from "../../shared/LoadFail";
