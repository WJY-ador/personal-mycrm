// 막대 한 줄씩(옛 barRows) — 숫자는 글자로 보이고 막대는 꾸밈(aria-hidden). 「나」 출처 문맥·활동 현황이 같이 쓴다.
export type Bar = { label: string; n: number; href?: string };

export function Bars({ rows, empty }: { rows: Bar[]; empty: string }) {
  if (!rows.length) return empty ? <div className="empty">{empty}</div> : null;
  const max = rows.reduce((m, r) => Math.max(m, r.n), 0);
  return (
    <ul className="bars">{rows.map((r, i) => (
      <li key={i}>{r.href ? <a href={r.href}>{r.label}</a> : <span>{r.label}</span>}
        <span className="bar" aria-hidden="true"><i style={{ width: `${max ? Math.max(2, Math.round(r.n / max * 100)) : 0}%` }} /></span><b>{r.n}</b></li>
    ))}</ul>
  );
}
