// 문의를 보낸 자리(page — 서버 db.TICKET_PAGES 안) — 옛 deskPage 그대로: 판단 대조 = review, 사용자 탭 = 질문형 question·기록형 record,
// 옛 화면(#q·#journal·#structure·#map) = 그 이름, 그 밖(나·오늘·설정…) = other. 순서 = 껍데기 pickTab(탭 줄 → 사용자 탭 → 옛 화면)
import { readOk, type AppState } from "../../shared/state";

const BASE_PAGE: Record<string, string> = { q: "question", journal: "record", structure: "structure", map: "map" };

export function deskPage(S: AppState | undefined, hash: string): string {
  if (!S) return "other";
  const [tab = "", a = ""] = decodeURIComponent(hash.replace(/^#/, "")).split("/");
  if (a === "review") return "review";
  if (tab === "_me" || tab === "_today") return "other";
  const u = readOk(S, "tabs") ? (S.tabs || []).find(t => t.id === tab) : undefined;
  if (u) return (u.blocks || [])[0] === "journal" ? "record" : "question";
  return BASE_PAGE[tab] || "other";
}

export const bytes = (s: string) => new TextEncoder().encode(s).length;
export const clip = (s: string, n: number) => (s.length > n ? s.slice(0, n) + "…" : s);
