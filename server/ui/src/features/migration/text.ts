// 이관 화면 문구·고정 값(옛 app.html 「이관」 절 글자 그대로). 서버 사유 코드는 사람 말 + 코드(작게)
import type { ApiError } from "../../shared/api";
import { postMsg } from "../../shared/postErr";

export const MIG_STATE: Record<string, [string, string]> = {
  staged: ["st-wait", "올리는 중"], sealed: ["st-wait", "확인 대기"], applied: ["st-mine", "반영함"], cancelled: ["st-off", "취소함"], expired: ["st-off", "만료"], reverted: ["st-off", "되돌림"],
};
export const MIG_ACTIONS = ["insert", "noop", "warn", "conflict", "reject"];
export const MIG_ACT: Record<string, string> = { insert: "새로 넣기", noop: "이미 있음", warn: "중복 의심", conflict: "충돌", reject: "거절" };
export const MIG_RESULTS = ["applied", "noop", "skipped_unchecked", "skipped_warn", "skipped_conflict", "skipped_reject"];
export const MIG_RES: Record<string, string> = {
  applied: "반영함", noop: "이미 있음", skipped_unchecked: "체크 안 함", skipped_warn: "중복 의심, 건너뜀", skipped_conflict: "충돌, 건너뜀", skipped_reject: "거절, 건너뜀",
};
export const MIG_WHY: Record<string, string> = {
  unit_deferred: "이번 이관 대상이 아닌 자료군", review_pending: "검토가 끝나지 않음", sensitivity_internal: "내부 자료",
  provenance_unknown: "출처 정보에 모르는 값이 있음", scope_self_only: "내 글만 받음", provenance_contradiction: "출처 정보가 서로 맞지 않음",
  file_mtime_not_allowed: "파일 수정 시각은 날짜로 쓸 수 없음", date_invalid: "날짜 형식이 틀림", content_hash_mismatch: "본문 확인 값이 맞지 않음",
  url_not_allowed: "웹 주소가 있음", email_not_allowed: "이메일 주소가 있음", path_not_allowed: "로컬 경로가 있음", body_empty: "본문이 비어 있음",
  dependency_cycle: "서로 가리키는 고리", duplicate_content: "같은 내용이 다른 항목으로 있음", "ref-not-found": "가리키는 항목을 찾을 수 없음",
};
export const MIG_LEAD = "PC에 모아 둔 옛 자료를 이 계정으로 옮겨요. PC 업로더가 올린 plan을 여기서 항목마다 확인한 뒤 [반영]해요. 반영은 웹에서만 해요.";
export const MIG_TOK_WARN = "새로 발급하면 이전 토큰은 폐기돼요.";
export { LOADING } from "../../shared/words";
export const ASK = {
  tokNew: `새 이관 토큰을 발급할까요? ${MIG_TOK_WARN} PC 업로더에 새 토큰을 넣어야 해요.`,
  tokRevoke: "이 이관 토큰을 폐기할까요? 바로 쓸 수 없게 되고 되살릴 수 없어요.",
  cancel: "이 plan을 취소할까요? 올린 본문을 바로 지우고 되돌릴 수 없어요. 다시 하려면 PC에서 다시 올려요.",
};
export const DONE = {
  tokNew: "새 이관 토큰을 발급했어요. 지금 옮겨 두세요.", tokRevoke: "이관 토큰을 폐기했어요.", cancel: "plan을 취소했어요. 올린 본문을 지웠어요.",
  apply: "반영했어요. 영수증을 확인하세요.", again: "이미 반영한 plan이에요. 같은 영수증을 보여 줘요.",
};
export const OFF = {
  list: "지금은 이관이 꺼져 있어요. 운영자가 켜면 이관 토큰을 발급하고 plan을 반영할 수 있어요. 지난 plan과 영수증은 아래에서 볼 수 있어요.",
  deny: "이 계정은 이관 허용 목록에 없어요. 운영자에게 허용 목록에 넣어 달라고 하세요. 지난 plan과 영수증은 아래에서 볼 수 있어요.",
  plan: "지금은 이관이 꺼져 있거나 이 계정이 허용 목록에 없어 기준 체크와 반영을 할 수 없어요. 운영자가 켜면 다시 해 주세요.",
};

// 토큰 발급·폐기 실패 — 스위치 두 가지만 화면 말, 그 밖은 서버 문구(옛 migPlain)
export const plainErr = (e: ApiError) =>
  e.code === "MIGRATION-OFF" ? "지금은 이관이 꺼져 있어요." : e.code === "MIGRATION-NOT-ALLOWED" ? "이 계정은 이관 허용 목록에 없어요." : postMsg(e);
