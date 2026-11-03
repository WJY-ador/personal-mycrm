// 자료 종류 화면 문구·고정 값(옛 app.html renderObjects·renderPeople·renderSources·renderRefl* 글자 그대로).
// 여러 화면이 같이 쓰는 낱말(REFL_KIND·SRC_KIND·TRASH_ASK·LOADING)은 shared 에서 다시 내보낸다.
export { SRC_KIND } from "../../shared/source";
export { REFL_KIND } from "../../shared/words";
export const REFL_REVIEW: Record<string, [string, string]> = { pending: ["b-wait", "확인 전"], reviewed: ["b-mine", "확인했어요"] };
export const REFL_HELP = "출처를 접한 뒤 내가 한 생각만 적어요. 다른 사람의 말·경험·생각을 옮기는 곳이 아니에요.";
export const PERSON_HELP = "별칭도 그 사람을 알아볼 수 있으면 개인정보예요.";
export const REVIEW_NOTE = "「확인했어요」는 판단 확정이 아니고 근거로 인용하지 않아요.";
export { TRASH_ASK, TRASH_DONE } from "../../shared/item";
export { LOADING } from "../../shared/words";
export const HOME: [string, string] = ["#_obj", "자료 종류"];
