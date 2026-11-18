// 축 코드 칩 — 수집 글 행(오늘 수집 인박스 카드, 「나」 목록 보기)에 그 글의 축 코드를 다(여러 개면 다). 이름은 title(마우스).
import type { axisCodes } from "./axes";

export function AxisCodes({ codes }: { codes: ReturnType<typeof axisCodes> }) {
  if (!codes.length) return null;
  return <span className="axcodes">{codes.map(c => (
    <span key={c.id} className="chip axcode" title={c.title || undefined}>{c.code}</span>
  ))}</span>;
}
