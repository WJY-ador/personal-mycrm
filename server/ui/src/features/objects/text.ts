// 자료 종류 화면 문구·고정 값(옛 app.html renderObjects·renderPeople·renderSources·renderRefl* 글자 그대로).
// REFL_KIND·SRC_KIND·TRASH_ASK·LOADING 등은 다른 옛 화면·「나」에 같은 값이 있다(R5 정리 — server/ui/migrated.json temp_duplicates).
export { SRC_KIND } from "../../shared/source";
export const REFL_KIND: Record<string, string> = { summary: "내 요약", reaction: "내 반응" };
export const REFL_REVIEW: Record<string, [string, string]> = { pending: ["b-wait", "확인 전"], reviewed: ["b-mine", "확인했어요"] };
export const REFL_HELP = "출처를 접한 뒤 내가 한 생각만 적어요. 다른 사람의 말·경험·생각을 옮기는 곳이 아니에요.";
export const PERSON_HELP = "별칭도 그 사람을 알아볼 수 있으면 개인정보예요.";
export const REVIEW_NOTE = "「확인했어요」는 판단 확정이 아니고 근거로 인용하지 않아요.";
export { TRASH_ASK, TRASH_DONE } from "../../shared/item";
export const LOADING = "불러오는 중이에요…";
export const HOME: [string, string] = ["#_obj", "자료 종류"];
