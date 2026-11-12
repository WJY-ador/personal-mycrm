// 「오늘」·저장 승인 대기 문구·고정 값(옛 app.html renderToday2·renderInbox·inboxOne 글자 그대로). LOADING·ME_EMPTY = shared/words(「나」와 같은 값 한 벌).
import type { AppState } from "../../shared/state";
import type { Entry } from "./todayApi";

export { LOADING } from "../../shared/words";
export { ME_EMPTY } from "../../shared/words";
export const SELF_NOTE = "승인하면 이 글을 내 글로 저장해요. 글에 다른 사람의 실명, 연락처, 발언, 고객사 정보가 있으면 그대로 서버에 저장돼요. 승인 전에 내용을 확인해 주세요.";
export const INBOX_KIND: Record<string, string> = { self_text: "내 글", self_summary: "내 글 AI 요약" };
export const INBOX_STATE: Record<string, string> = { pending: "대기", applied: "승인함", excluded: "제외함", expired: "만료", all: "전체" };
export const GEN_LABEL: [keyof NonNullable<Entry["generation"]>, string][] = [["method", "만든 방법"], ["tool", "도구"], ["model", "모델"], ["input_scope", "입력 범위"], ["inputs", "입력 수"]];
// 생성 정보 값 → 사람 말(계약 canon-inbox/1 의 열거값). 모르는 값은 「기타」 + 원값 작게. 도구·모델은 장치가 신고한 코드 그대로
export const GEN_VALUE: Record<string, Record<string, string>> = { method: { ai_summary: "AI 요약", none: "없음(직접 씀)" }, input_scope: { self_only: "내 글만" } };
export const SHOW = 5;   // 날짜 머리글당 활동 줄(그 밖은 「더 N」)

// 제목 — 대기 본문(제목 포함)은 승인·제외·만료 때 지워진다. 승인했으면 저장된 글 제목, 아니면 사람 말로
export function inboxTitle(S: AppState, e: Entry): string {
  if (e.title) return e.title;
  const r = e.target_record_id ? (S.journal || []).find(j => j.id === e.target_record_id) : null;
  if (r && r.title) return r.title;
  return e.state === "pending" ? "(제목 없음)" : "(대기 본문을 지웠어요)";
}
