// 수집 인박스 묶기·문구 — 등급 묶음(신호, 소식, 노이즈, 등급 없음) 순, 묶음 안 collected_on 내림차순, 같으면 id. 머리 = 보이는 글 기준.
import type { Post } from "./collectedApi";

export const GRADES: [string, string][] = [["signal", "신호"], ["news", "소식"], ["noise", "노이즈"], ["", "등급 없음"]];
export const BULK_GRADES = new Set(["news", "noise"]);   // 묶음 머리에 「전부 버림」
export const CHANNEL: Record<string, string> = { linkedin: "LinkedIn", reddit: "Reddit", kakao: "카카오톡", threads: "Threads", blog: "블로그", web: "웹" };
export { AI_MARK } from "../../shared/words";
export const NO_BODY = "원문 본문은 서버에 없어요. 원문은 원문 링크나 PC의 대시보드에서 봐요.";
export const UNDO_MS = 5000;
// 읽기 판 긴 요약 상태 문구(2026-11-25 구현계획 4절) — 상태 열쇠 = useLong 의 Long
export const LONG_TEXT: Record<string, string> = {
  auto: "끌어 놓으면 요약을 만들어요.",
  wait: "PC에서 요약을 만드는 중이에요.",
  slow: "PC 앱이 꺼져 있거나 AI 연결이 안 되어 있어요. 켜지면 이어서 만들어요.",
  nodevice: "연결된 PC가 없어 요약을 만들 수 없어요.",
  short: "원문이 짧아 긴 요약을 만들지 않았어요.",
  fail: "요약을 만들지 못했어요.",
};

const gradeOf = (p: Post) => (p.ai.grade && GRADES.some(([g]) => g === p.ai.grade) ? p.ai.grade : "");
// AI 긴 요약(as-is, to-be, 운영, 요점 중 하나라도) 있음 — 읽기 판 표시와 요청 여부가 같은 판정을 쓴다
export const hasLong = (p: Post) => !!(p.ai.as_is || p.ai.to_be || p.ai.ops || (p.ai.points || []).some(Boolean));
export const safeUrl = (u: string | null) => (u && u.startsWith("https://") ? u : null);   // 서버가 https 만 받는다 — 화면도 같은 꼴만 링크로

export function byCollected(a: Post, b: Post) {
  return (b.collected_on || "").localeCompare(a.collected_on || "") || a.id.localeCompare(b.id);
}

export function groups(posts: Post[]): { grade: string; label: string; posts: Post[] }[] {
  return GRADES.map(([grade, label]) => ({ grade, label, posts: posts.filter(p => gradeOf(p) === grade).sort(byCollected) })).filter(g => g.posts.length);
}

export function headline(posts: Post[]): string {
  const signal = posts.filter(p => gradeOf(p) === "signal").length, none = posts.filter(p => gradeOf(p) === "").length;
  return `수집 ${posts.length}건 (신호 ${signal}), 등급 없음 ${none}`;
}
