// 수집 인박스 묶기·문구 — 등급 묶음(신호, 소식, 노이즈, 등급 없음) 순, 묶음 안 collected_on 내림차순, 같으면 id. 머리 = 보이는 글 기준.
import type { Post } from "./collectedApi";

export const GRADES: [string, string][] = [["signal", "신호"], ["news", "소식"], ["noise", "노이즈"], ["", "등급 없음"]];
export const BULK_GRADES = new Set(["news", "noise"]);   // 묶음 머리에 「전부 버림」
export const CHANNEL: Record<string, string> = { linkedin: "LinkedIn", reddit: "Reddit", kakao: "카카오톡", threads: "Threads", blog: "블로그", web: "웹" };
export const AI_MARK = "AI 요약";
export const NO_BODY = "원문 본문은 서버에 없어요. 원문은 원문 링크나 PC의 대시보드에서 봐요.";
export const UNDO_MS = 5000;

const gradeOf = (p: Post) => (p.ai.grade && GRADES.some(([g]) => g === p.ai.grade) ? p.ai.grade : "");
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
