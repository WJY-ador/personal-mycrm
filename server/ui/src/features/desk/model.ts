// 문의를 보낸 자리(page — 서버 db.TICKET_PAGES 안): 판단 대조 = review, 사용자 탭 = 질문형 question·기록형 record,
// 옛 화면(#q·#journal·#structure·#map) = 그 이름, 그 밖(나·오늘·설정…) = other. 탭 고르기는 껍데기 라우터와 같은 판정 한 벌(shared/route pickTab)
import { parseHash, pickTab } from "../../shared/route";
import type { AppState } from "../../shared/state";

const PAGE: Record<string, string> = { question: "question", record: "record", structure: "structure", map: "map" };

export function deskPage(S: AppState | undefined, hash: string): string {
  if (!S) return "other";
  const R = parseHash(hash);
  if (R.a === "review") return "review";
  return PAGE[pickTab(R, S).view] || "other";
}

export const bytes = (s: string) => new TextEncoder().encode(s).length;
