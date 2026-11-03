// 서버 시각은 UTC(ISO, 오프셋 포함) — 보는 사람의 시간대로 그린다. 옛 app.html mdhm 과 같은 꼴(「10월 23일 10:00」).
const pad2 = (n: number) => String(n).padStart(2, "0");

export function mdhm(iso: string | null | undefined): string {
  const d = new Date(iso || "");
  return isNaN(d.getTime()) ? "" : `${d.getMonth() + 1}월 ${d.getDate()}일 ${pad2(d.getHours())}:${pad2(d.getMinutes())}`;
}
