// 웹 「대화」(구독 AI 채팅) 문구 — 서버 오류 코드 → 사용자 문장. 모르는 코드 = 서버 msg.
export const TEXT_MAX = 8000;   // server/webchat.py TEXT_MAX_CHARS 와 같은 값
export const TITLE = "AI 대화";
export const EMPTY = "연결된 AI와 자유롭게 대화해요. MyCRM 작업은 기존 도구 권한과 확인 규칙을 따릅니다.";
export const PC_ON = "PC 연결됨";
export const PC_OFF = "PC 꺼짐 — PC 에서 my-crm 에이전트 대화를 켜세요";
export const WAITING = "답을 기다리는 중…";
export const KEEP = "대화 기록은 서버에 30일 보관돼요.";
export const REPLACED = "다른 탭에서 이 대화를 열었어요. 여기서 이어 하려면 닫았다가 다시 여세요.";
export const TRIMMED = "앞의 대화는 생략했어요(최근 대화만 보여요).";
export const END: Record<string, string> = {
  STOPPED: "중지했어요.", "TURN-LIMIT": "답이 너무 길어 멈췄어요.", "TURN-TIMEOUT": "PC 응답이 없어 끝냈어요.",
  "DEVICE-OFFLINE": "PC 연결이 끊겨 보내지 못했어요.", "BUFFER-LIMIT": "PC 가 보낼 출력이 너무 많아 멈췄어요.", "PC-BUSY": "PC 가 다른 답을 만드는 중이에요.",
};
export const ERR: Record<string, string> = {
  CONSENT_REQUIRED: "PC에서 이 대화를 허용하는 절차가 아직 준비되지 않아 현재는 사용할 수 없어요.",
  "TURN-BUSY": "앞 답이 끝난 뒤 보내세요.", "DEVICE-OFFLINE": "PC 가 연결돼 있지 않아요.", "NO-DEVICE": "연결된 PC 가 없어요. 연결 장치에서 PC 를 연결하세요.",
  OFFLINE: "서버에 연결하지 못했어요. 연결을 확인한 뒤 다시 시도하세요.", "PROVIDER-UNAVAILABLE": "이 대화에 선택한 AI 또는 모델을 사용할 수 없어요. 새 대화에서 제공되는 선택을 확인하세요.",
  "SESSION-CONFLICT": "다른 대화가 먼저 시작됐어요. 기존 대화를 다시 열거나 새로고침하세요.",
  "DEVICE-REQUIRED": "연결된 PC 가 여러 대예요.", "DEVICE-GONE": "이 대화의 PC 연결이 해제됐어요. 다시 열면 새 대화가 시작돼요.",
  "SESSION-CLOSED": "끝난 대화예요. 다시 열면 새 대화가 시작돼요.", "RATE-LIMIT": "잠시 뒤 다시 보내세요(1분에 6번).",
  "TEXT-LIMIT": `한 번에 ${TEXT_MAX.toLocaleString()}자까지 보낼 수 있어요.`, "SWITCH-OFF": "대화 기능이 지금 꺼져 있어요.",
};
export const errText = (e: { code: string; msg: string }) => ERR[e.code] || e.msg || "보내지 못했어요. 다시 해 보세요.";
export const endText = (code: string) => END[code] || `답이 끝나지 못했어요(${code}).`;
