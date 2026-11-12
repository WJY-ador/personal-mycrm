// 웹 「대화」(구독 AI 채팅) 문구 — 서버 오류 코드 → 사용자 문장. 모르는 코드 = 서버 msg. 화면 글자는 이 파일에 모은다.
export const TEXT_MAX = 8000;   // server/webchat.py TEXT_MAX_CHARS 와 같은 값
export const TITLE = "AI 대화";
export const EMPTY = "연결된 AI와 대화해요. 기록을 남기거나 바꾸는 일은 MyCRM의 기존 권한과 확인 규칙을 따라요.";
export const PC_ON = "PC 연결됨";
export const PC_OFF = "PC 꺼짐";
export const WAITING = "답을 기다리는 중";
export const KEEP = "대화 기록은 서버에 30일 보관돼요.";
export const TOOLS_ONLY = "AI는 내 판단 대시보드의 도구만 써요.";
export const REPLACED = "다른 탭에서 이 대화를 열었어요. 여기서 이어 하려면 닫았다가 다시 여세요.";
export const TRIMMED = "앞의 대화는 생략했어요(최근 대화만 보여요).";
export const PLACEHOLDER = "오늘 있었던 일이나 궁금한 것을 적어 보세요";

// 모델 고르기 — 목록은 PC 가 알려 준 것(서버 capabilities)만
export const PICK = "모델 고르기";
export const PICK_SWITCH = "이 모델로 새 대화를 시작해요. 지금 대화는 지난 대화 목록에 남아요.";
export const PICK_SWITCH_GO = "새 대화 시작";
export const PICK_LOADING = "모델 목록을 불러오는 중이에요.";
export const NO_MODEL: Record<string, string> = {
  none: "연결된 PC가 없어요. 연결 장치에서 PC를 연결하면 모델을 고를 수 있어요.",
  offline: "PC 앱이 꺼져 있어요. PC에서 MyCRM 앱을 켜면 모델이 나타나요.",
  recent: "PC는 연결돼 있지만 대화에 쓸 수 있는 모델을 알려 오지 않았어요. PC 앱의 대화 기능이 꺼져 있거나 아직 지원을 준비하고 있어요.",
  "": "지금 고를 수 있는 모델이 없어요. PC 앱이 켜져 있는지 확인하세요.",
};
const PROVIDER: Record<string, string> = { claude: "Claude", codex: "Codex", fake: "시험용 가짜 AI" };
export const providerName = (p: string) => PROVIDER[p] || p;
export const modelLabel = (provider: string, model: string | null) => `${providerName(provider)}, ${model || "기본 모델"}`;
export const pcLabel = (i: number) => `PC ${i + 1}`;

// PC 허용(grant) 대기 — 새 PC 앱은 허용하지 않음을 서버에 알린다(declined). 0.1.3 이하 앱의 취소, 시간 초과는 closed 한 문장으로 둔다
export const GRANT: Record<string, string> = {
  asking: "PC 앱에 허용을 요청하는 중이에요.",
  none: "PC 앱에서 허용을 눌러 주세요. 허용 창이 곧 떠요.",
  open: "PC 앱에 허용 창이 떴어요. 허용을 눌러 주세요.",
  approved: "허용됐어요. 대화를 시작해요.",
  closed: "PC 앱에서 허용하지 않았거나 허용 창이 닫혔어요.",
  declined: "PC 앱에서 허용하지 않았어요. 다시 시작하려면 새 대화를 여세요.",
  expired: "허용을 기다리는 시간(5분)이 지났어요.",
  offline: "PC 앱이 꺼져 있거나 연결이 끊겼어요. PC 앱을 켠 뒤 다시 요청하세요.",
};
export const GRANT_RETRY = "다시 요청";
export const GRANT_CANCEL = "그만 기다리기";

// 지난 대화
export const HISTORY = "지난 대화";
export const NEW_CHAT = "새 대화";
export const HISTORY_EMPTY = "지난 대화가 없어요.";
export const HISTORY_NOTE = "대화 기록은 서버에 30일 보관한 뒤 지워져요. 지난 대화는 읽기만 할 수 있어요.";
export const HISTORY_NOW = "지금 대화";
export const PAST_NOTE = "지난 대화예요. 읽기만 할 수 있어요. 이어서 말하려면 새 대화를 시작하세요.";
export const PAST_EMPTY = "이 대화에는 남은 메시지가 없어요.";
export const BUSY_NEW = "답이 끝난 뒤 새 대화를 시작할 수 있어요.";

// 확인 카드 — 확인 카드 대상 op(server/webchat.py CHAT_CARD_OPS) 24개 = decide 10 + write 14. 모르는 op = op 이름 그대로.
// 키 집합은 서버, agent/chat_approval_context.py 와 같아야 한다(server/test_chat_injection.py 가 대조한다)
export const OP_NAME: Record<string, string> = {
  record_edit: "기록 고치기", record_provenance_set: "기록 작성자 표시 바꾸기", candidate_decide: "판단 후보 정하기",
  definition_archive: "자료 종류 보관하기", definition_restore: "자료 종류 보관 풀기", person_delete: "사람 지우기",
  source_reflection_review: "읽고 든 생각 검토 표시 바꾸기", source_reflection_delete: "읽고 든 생각 지우기",
  trash_move: "휴지통으로 옮기기", trash_restore: "휴지통에서 되살리기",
  layout_set: "화면 배치 바꾸기", layout_reset: "화면 배치 처음으로", display_name_set: "표시 이름 바꾸기",
  question_add: "질문 더하기", profile_set: "프로필 항목 저장하기", record_add: "기록 남기기",
  record_attach: "기록 붙일 곳 정하기", record_title_set: "기록 제목 바꾸기", candidates_propose: "판단 후보 제안하기",
  definition_propose: "자료 종류 제안하기", item_propose: "항목 제안하기", person_save: "사람 저장하기",
  source_create: "출처 만들기", source_reflection_save: "읽고 든 생각 저장하기",
};
export const CARD_HEAD = "확인이 필요한 작업";
export const CARD_MORE = "자세히";
export const CARD_SHOWN = "실행할 내용";
export const CARD_RAW: Record<string, string> = { shown: "화면에 보인 내용(원본)", impact: "영향(원본)", params: "실행할 매개변수(원본)", result: "실행 결과(원본)" };
export const CARD_STATUS: Record<string, string> = { pending: "확인 대기", confirmed: "확인해 실행함", cancelled: "취소함" };
export const CARD_IRREVERSIBLE = "되돌릴 수 없음";
export const CARD_NULL = "없음";
export const CARD_EMPTY = "빈 값";

export const END: Record<string, string> = {
  STOPPED: "중지했어요.", "TURN-LIMIT": "답이 너무 길어 멈췄어요.", "TURN-TIMEOUT": "PC 응답이 없어 끝냈어요.",
  "DEVICE-OFFLINE": "PC 연결이 끊겨 보내지 못했어요.", "BUFFER-LIMIT": "PC 가 보낼 출력이 너무 많아 멈췄어요.", "PC-BUSY": "PC 가 다른 답을 만드는 중이에요.",
};
export const PAST_END: Record<string, string> = { failed: "답이 끝나지 못했어요.", stopped: "중지했어요." };
export const ERR: Record<string, string> = {
  CONSENT_REQUIRED: "이 대화의 PC 허용이 끝났어요(화면 잠금 등). 새 대화를 시작하면 PC 앱에서 다시 허용할 수 있어요.",
  "GRANT-EXPIRED": "PC 허용 시간이 지났어요. 다시 요청하세요.", "GRANT-USED": "이미 쓴 PC 허용이에요. 다시 요청하세요.",
  "GRANT-INVALID": "이 선택에 맞는 PC 허용이 없어요. 다시 요청하세요.",
  "TURN-BUSY": "앞 답이 끝난 뒤 보내세요.", "DEVICE-OFFLINE": "PC 가 연결돼 있지 않아요.", "NO-DEVICE": "연결된 PC 가 없어요. 연결 장치에서 PC 를 연결하세요.",
  OFFLINE: "서버에 연결하지 못했어요. 연결을 확인한 뒤 다시 시도하세요.", "PROVIDER-UNAVAILABLE": "고른 AI 또는 모델을 지금 쓸 수 없어요. 모델 고르기에서 다시 고르세요.",
  "SESSION-CONFLICT": "다른 대화가 먼저 시작됐어요. 기존 대화를 다시 열거나 새로고침하세요.",
  "DEVICE-REQUIRED": "연결된 PC 가 여러 대예요.", "DEVICE-GONE": "이 대화의 PC 연결이 해제됐어요. 다시 열면 새 대화가 시작돼요.",
  "SESSION-CLOSED": "끝난 대화예요. 새 대화를 시작하세요.", "RATE-LIMIT": "잠시 뒤 다시 보내세요(1분에 6번).",
  "TEXT-LIMIT": `한 번에 ${TEXT_MAX.toLocaleString()}자까지 보낼 수 있어요.`, "SWITCH-OFF": "대화 기능이 지금 꺼져 있어요.",
};
export const errText = (e: { code: string; msg: string }) => ERR[e.code] || e.msg || "보내지 못했어요. 다시 해 보세요.";
export const endText = (code: string) => END[code] || `답이 끝나지 못했어요(${code}).`;
