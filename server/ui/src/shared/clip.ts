// 긴 글 줄이기(옛 clip) · 질문 번호(옛 qNo — 질문 없음·찾을 수 없음 Q?) · 대조 경로 목록 키(질문 있으면 질문 id, 없으면 r:<글 id>)
import type { AppState, Cand } from "./state";

export const clip = (s: string | null | undefined, n: number) => { const t = String(s || ""); return t.length > n ? t.slice(0, n) + "…" : t; };
export const NO_QUESTION = "질문 없음";
export function qNo(S: AppState, id: string | null) {
  if (!id) return NO_QUESTION;
  const i = (S.questions || []).findIndex(q => q.id === id);
  return i < 0 ? "Q?" : `Q${i + 1}`;
}
export const listKey = (c: Pick<Cand, "question_id" | "record_id">) => c.question_id || `r:${c.record_id}`;
export const reviewHref = (tabId: string, c: Cand) => `#${tabId}/review/${listKey(c)}/${c.id}`;
export const byNewest = (a: { updated?: string; created?: string }, b: { updated?: string; created?: string }) =>
  String(b.updated || b.created || "").localeCompare(String(a.updated || a.created || ""));
