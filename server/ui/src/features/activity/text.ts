// 활동 화면 문구·고정 값(옛 app.html 「board 이전」 절 글자 그대로). 옛 쪽에 같은 이름이 남은 것(ROLE_LABEL·LOADING·TRASH_ASK)은
// 다른 옛 화면(사람·출처 상세·오늘)이 쓰는 일시 중복 — R5 에서 한쪽만(server/ui/migrated.json temp_duplicates).
export const ME_NOTICE = "연결된 활동과 내 글을 정해진 계산 규칙으로 보여 줍니다. 활동량을 성격이나 능력으로 해석하지 않습니다. AI가 작성한 설명은 저장 승인 대기에 표시합니다.";
export const RAW_LOCAL = "원문을 보관한 PC에서 열 수 있습니다";
export const RAW_PORT_KEY = "crm-raw-port";
export const RAW_PORT_DEFAULT = 8790;   // 로컬 에이전트(agent/) 원문 뷰어 기본 포트와 같다(board-dev 8787 을 피함)
export const PERIODS: [string, string][] = [["7d", "최근 7일"], ["30d", "최근 30일"], ["90d", "최근 90일"], ["all", "전체"]];
export const LOADING = "불러오는 중이에요…";
export const MORE_FAIL = "더 불러오지 못했어요. 다시 눌러 주세요.";
export const LIST_HINT = "PC의 로컬 에이전트가 보낸 행동이에요. 원문은 PC에 남고, 여기엔 행동·날짜·별칭·출처 종류만 있어요.";
export { TRASH_ASK, TRASH_DONE } from "../../shared/item";
export const HELP = {
  axisSum: "축이 여러 개인 활동은 축마다 한 번씩 세요. 축별 합계가 전체와 다를 수 있어요.",
  people: "좋아요·리포스트·댓글·답장에서 글쓴이·상대로 연결된 별칭만 세요. 사람마다 한 번씩이라 합계는 전체 활동량이 아니에요.",
  undated: "행동한 날을 알 수 없어 기간 집계에서 뺀 활동이에요(기간과 무관한 전체). 아래 날짜는 처음 수집한 날 — 행동한 날이 아니라 PC 수집기가 처음 본 날이에요.",
  grounds: (rule: string) => `확정한 ${rule}에 연결된 현재 글 수·활동 수예요(연결을 최대 2단계까지 따라가요).`,
};

