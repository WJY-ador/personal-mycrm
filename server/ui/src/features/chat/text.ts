// 대화 서랍 문구·고정 값(옛 app.html 대화 절 글자 그대로).
export const CHAT_MAX = 8000;   // 서버 JOB_TEXT_MAX_CP 와 같은 기준(코드포인트)
export const CHAT_WAIT = ["queued", "leased", "running"];
export const UNIT_JOIN = "\n\n";   // 정리 글 = units.text 를 이 구분으로 결합(PC stack/1 과 같은 값)
// 장치 없음(③-0.2) — PRD 1-2 고정 문구(글자 그대로, 한 곳)
export const CHAT_NODEV = "이 기능은 본인 PC에서 본인 Claude 구독으로 실행하며, PC 연결과 에이전트 실행이 필요합니다.";
export const CHAT_DONE: Record<string, string> = {
  failed: "정리하지 못했어요. 다시 보내 주세요.", cancelled: "작업이 취소됐어요. 다시 보내 주세요.",
  expired: "대화가 만료됐어요(첫 입력 뒤 24시간). 새로 시작해 주세요.", needs_check: "PC 쪽 정리가 끝났는지 알 수 없어요. 연결 장치를 확인한 뒤 다시 보내 주세요.",
  confirmed: "이미 확정한 대화예요.",
};
export const CHAT_ERR: Record<string, string> = {
  OFFLINE: "서버에 연결하지 못했어요. 잠시 뒤 다시 해 보세요.", "SWITCH-OFF": "대화가 지금 꺼져 있어요.",
  "RATE-LIMIT": "요청이 많아요. 잠시 뒤 다시 해 보세요.", "JOB-LIMIT": "진행 중인 작업이 많아요. 끝난 뒤 다시 보내 주세요.",
  "PAYLOAD-LIMIT": `글이 너무 길어요(${CHAT_MAX.toLocaleString()}자까지). 줄이거나 나눠서 보내 주세요.`,
};
export const EMPTY_TURNS = "말하거나 원문을 붙여 넣으면 PC 가 내 구조에 맞춰 정리해요. 정리한 글을 한 번 확인하면 저장돼요.";
export const EDITED = "고친 글은 입력 칸을 벗어나면 다시 정리해요.";
export const STALE = "이 결과는 최신이 아니에요. 최신 상태를 불러올게요.";
export const NEWER = "다른 탭에서 더 새로 정리했어요 — 최신 결과로 바꿨어요.";
export const cp = (s: string | null | undefined) => [...String(s || "")].length;
