// 한판 상세의 선(넓은 화면만) — 출처 카드(data-k) 오른쪽 가운데에서 소제목 카드(data-o) 왼쪽 가운데로 곡선. 강조 = hot 소제목의 선만 진하게.
// 격자 = 이 svg 의 부모(부모 ref 는 자식 효과보다 늦게 붙는다 — 자기 ref 로 찾는다). 위치는 그리기 뒤에 잰다(창 크기, 카드 펼침이 바뀌면 다시) — 선 개수와 강조는 links 데이터 그대로라 위치를 못 재도(시험 환경) 같다.
import { useId, useLayoutEffect, useRef, useState } from "react";
import type { Link } from "./boardModel";
import css from "./Board.module.css";

type Geo = { d: string; x: number; y: number };

function measure(g: HTMLElement, links: Link[]): Geo[] {
  const G = g.getBoundingClientRect();
  return links.map(({ o, k }) => {
    const s = g.querySelector(`[data-k="${k}"]`)?.getBoundingClientRect(), t = g.querySelector(`[data-o="${o}"]`)?.getBoundingClientRect();
    if (!s || !t) return { d: "", x: 0, y: 0 };
    const x1 = s.right - G.left, y1 = s.top - G.top + s.height / 2, x2 = t.left - G.left - 4, y2 = t.top - G.top + t.height / 2, dx = Math.max(40, (x2 - x1) / 2);
    return { d: `M${x1} ${y1} C${x1 + dx} ${y1} ${x2 - dx} ${y2} ${x2} ${y2}`, x: x1, y: y1 };
  });
}

export function BoardLinks({ links, hot, ver }: { links: Link[]; hot: number | null; ver: string }) {
  const [geo, setGeo] = useState<Geo[]>([]), mid = useId().replace(/:/g, ""), svg = useRef<SVGSVGElement>(null);
  useLayoutEffect(() => {
    const g = svg.current?.parentElement;
    if (!g) return;
    const draw = () => setGeo(prev => { const next = measure(g, links); return JSON.stringify(next) === JSON.stringify(prev) ? prev : next; });
    draw();
    window.addEventListener("resize", draw);
    const ro = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(draw);
    ro?.observe(g);
    g.querySelectorAll("[data-k], [data-o]").forEach(n => ro?.observe(n));   // 카드 펼침 = 그 카드 크기가 바뀐다
    return () => { window.removeEventListener("resize", draw); ro?.disconnect(); };
  }, [links, ver]);
  return (
    <svg ref={svg} className={css.links} aria-hidden="true">
      <defs><marker id={`lar${mid}`} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" /></marker></defs>
      {links.map((l, i) => { const p = geo[i] || { d: "", x: 0, y: 0 }, on = hot === l.o ? css.on : undefined;
        return <g key={`${l.o}${l.k}`} data-lo={l.o} data-lk={l.k} className={on}>
          <path className={css.ln} d={p.d || "M0 0"} markerEnd={`url(#lar${mid})`} /><circle className={css.p0} cx={p.x} cy={p.y} r={4.5} /></g>; })}
    </svg>
  );
}
