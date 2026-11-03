// 위치 줄(옛 crumbs) — [주소, 이름] 목록. 주소가 빈 칸 = 지금 자리(글자만)
export function Crumbs({ xs }: { xs: [string, string][] }) {
  return (
    <nav className="crumbs" aria-label="위치">{xs.map(([h, l], i) => (
      <span key={i} style={{ display: "contents" }}>{i ? <span>›</span> : null}{h ? <a href={h}>{l}</a> : <span>{l}</span>}</span>
    ))}</nav>
  );
}
