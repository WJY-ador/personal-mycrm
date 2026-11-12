// 연결 장치 문구(옛 app.html 「연결 장치」 절 글자 그대로)
export const LEAD = "PC의 로컬 에이전트를 이 계정에 연결해요. 원문, 실명, 주소는 PC에 남고, 서버엔 행동, 날짜, 별칭, 출처 종류 같은 구조화 정보와 내가 승인할 글만 와요.";
export { LOADING } from "../../shared/words";
export const ASK = {
  reissue: "토큰을 다시 발급할까요? 지금 토큰은 바로 쓸 수 없게 돼요. PC의 로컬 에이전트에 새 토큰을 넣어야 해요. 이 PC의 AI 대화 허용도 함께 해제돼요.",
  revoke: "이 장치 연결을 해제할까요? 토큰을 바로 쓸 수 없게 되고 되살릴 수 없어요(새로 연결해야 해요). 이미 받은 활동과 글은 남아요. 이 PC의 AI 대화 허용도 함께 해제돼요.",
};
export const DONE = {
  connect: "장치를 연결했어요. 토큰을 지금 옮겨 두세요.",
  reissue: "토큰을 다시 발급했어요. 새 토큰을 지금 옮겨 두세요.",
  revoke: "연결을 해제했어요.",
  policy: "허용 규칙을 바꿨어요. 다음 업로드부터 적용돼요.",
  permit: "AI 대화 허용을 해제했어요. 다음에 쓸 때 PC 앱에서 다시 허용해요.",
};

// AI 대화 허용(대화 하나로 J, JD2, JD3) — PC와 AI 종류마다 한 번 허용하면 화면 잠금, 앱 재시작 뒤에도 다시 묻지 않는다. 끄는 길은 사람이 직접 하는 해제다
const AI: Record<string, string> = { claude: "Claude", codex: "Codex" };
export const aiName = (p: string) => AI[p] || p;
export const PERMIT_NOTE = (names: string) => `이 PC에서 ${names} 대화를 허용했어요. 화면을 잠그거나 PC 앱을 다시 켜도 다시 묻지 않아요. 자리를 비울 때 걱정되면 해제해 두세요.`;
export const PERMIT_BTN = (p: string) => `이 PC의 ${aiName(p)} 대화 허용 해제`;
export const PERMIT_ASK = (p: string) => `이 PC의 ${aiName(p)} 대화 허용을 해제할까요? 열려 있는 ${aiName(p)} 대화는 더 이어지지 않고, 다음에 쓸 때 PC 앱에서 다시 허용해야 해요.`;
