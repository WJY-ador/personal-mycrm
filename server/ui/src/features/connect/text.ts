// 설정 AI 앱 연결(#_setup/connect, 2026-11-23 4차) 문구. 연결 방법 세 줄은 guides/09 1절 표의 Claude, Claude Code, ChatGPT 줄 그대로(주소만 이 서버 주소로).
// 안내 문장과 첫 마디는 옛 첫 기록 카드(요약 맨 위)에서 옮겼다
export const TITLE = "AI 앱 연결";
export const LEAD = "Claude나 ChatGPT에 이 주소를 커넥터로 더하고 첫 마디를 보내요.";
export const MCP_LABEL = "MCP 주소";
export const WAYS_TITLE = "연결 방법";
export const SAY_LABEL = "첫 마디";
export const FIRST_SAY = "오늘 있었던 일 기록 남길게.";
export const MORE = ["자세한 것은 ", "도움말", "에서 볼 수 있어요."] as const;
export const mcpUrl = () => location.origin + "/mcp";
