// 서버 시각은 UTC(ISO, 오프셋 포함) — 보는 사람의 시간대로 그린다. 옛 app.html md·mdhm·dOnly 와 같은 꼴(「10월 23일 10:00」).
const pad2 = (n: number) => String(n).padStart(2, "0");
const toDate = (iso: string | null | undefined) => { const d = new Date(iso || ""); return isNaN(d.getTime()) ? null : d; };

export function mdhm(iso: string | null | undefined): string {
  const d = toDate(iso);
  return d ? `${d.getMonth() + 1}월 ${d.getDate()}일 ${pad2(d.getHours())}:${pad2(d.getMinutes())}` : "";
}

export function md(iso: string | null | undefined): string {
  const d = toDate(iso);
  return d ? `${d.getMonth() + 1}월 ${d.getDate()}일` : "";
}

export const timeOf = (iso: string | null | undefined) => toDate(iso)?.getTime() || 0;

// "YYYY-MM-DD"(날짜만) → 「10월 20일」(올해가 아니면 연도까지)
export function dOnly(s: string | null | undefined): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(s || ""));
  if (!m) return "";
  const y = Number(m[1]);
  return `${y !== new Date().getFullYear() ? y + "년 " : ""}${Number(m[2])}월 ${Number(m[3])}일`;
}
