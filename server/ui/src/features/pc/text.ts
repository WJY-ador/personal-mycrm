// 설정 「이 PC」(앱 하나 자동 연결, 2026-11-13 명세 1.1, 1.2) — 앱에서 로그인하면 이 PC 가 자동으로 연결된다. 토큰, 장치 목록, 허용 규칙은 보이지 않는다
import type { PcPhase } from "../../shared/desktopPc";

export const TITLE = "이 PC";
export const LEAD = "MyCRM 앱에서 로그인하면 이 PC가 자동으로 연결돼요. 무엇을 모을지는 앱의 수집 설정이 정해요.";
export const NO_APP = "이 칸은 MyCRM 앱 안에서 보여요. 앱을 설치하고 로그인하면 따로 할 일 없이 연결돼요.";
export const DOWNLOAD = "앱 내려받기";
export const SYNC = "지금 동기화";
export const LOADING = "이 PC 상태를 확인하는 중이에요.";
export const BAD = "이 PC 상태를 읽지 못했어요. 앱을 다시 열어 보세요.";
export const PHASE: Record<PcPhase, string> = {
  ok: "연결됨", syncing: "동기화하는 중", failed: "마지막 동기화 실패", login: "로그인이 필요해요", stopped: "멈춤",
};
// 실패 코드(앱이 주는 고정 낱말 또는 서버 코드) → 이유 한 줄. 모르는 코드는 코드 그대로 보인다
const WHY: Record<string, string> = {
  busy: "다른 작업이 진행 중이었어요", login: "로그인이 끊겼어요", revoked: "이 PC 연결이 해제됐어요", offline: "인터넷 연결이 끊겼어요",
  limit: "연결된 PC가 5대를 넘었어요", name: "표시 이름이 아직 없어요", unknown: "알 수 없는 이유예요",
};
export const why = (code: string | null) => (code ? WHY[code] || `서버가 거절했어요(${code})` : "");
export const lastLine = (at: string, ok: boolean) => `마지막 동기화 ${at}, ${ok ? "성공" : "실패"}`;
export const NEVER = "아직 동기화하지 않았어요";
export const REPORT_NOTE = "오류가 나면 오류 코드만 운영자에게 자동으로 보내져요(기록 내용, 경로, 토큰은 보내지 않아요).";
