// 방사형 연결 그래프(SVG) — 중심 1 + 이웃(상한 안). 노드 = 링크(키보드 Tab·Enter). 라벨 2줄, 전체 이름은 <title>·목록 보기에서
import { lines, type Edge, type GNode } from "./links";
import css from "./Graph.module.css";

type Props = { center: GNode; nodes: GNode[]; edges: Edge[]; narrow: boolean; name: (n: GNode) => string };

function Label({ ls, x, y, anchor }: { ls: string[]; x: number; y: number; anchor: "start" | "middle" | "end" }) {
  return <text x={x.toFixed(1)} y={y.toFixed(1)} textAnchor={anchor}>{ls.map((l, i) => <tspan key={i} x={x.toFixed(1)} dy={i ? "1.2em" : "0"}>{l}</tspan>)}</text>;
}

export function Graph({ center, nodes, edges, narrow, name }: Props) {
  const n = nodes.length, W = narrow ? 420 : 640, H = narrow ? 400 : 460, cx = W / 2, cy = H / 2;
  const R = narrow ? (n <= 6 ? 80 : 95) : n <= 6 ? 120 : n <= 12 ? 150 : 180;
  const pos = nodes.map((nd, i) => { const a = -Math.PI / 2 + 2 * Math.PI * i / Math.max(n, 1); return { nd, a, x: cx + R * Math.cos(a), y: cy + R * Math.sin(a) }; });
  const at = new Map(pos.map(p => [p.nd.key, p]));
  const cl = lines(name(center), narrow);
  return (
    <svg className={`${css.graph}${narrow ? " " + css.narrow : ""}`} viewBox={`0 0 ${W} ${H}`} role="group" aria-label={`${name(center)}의 연결 그래프`}>
      <defs><marker id="harrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" /></marker></defs>
      <g>{edges.map((e, i) => {
        const p = at.get(e.node.key);
        if (!p) return null;
        const [x1, y1, x2, y2] = e.dir === "out" ? [cx, cy, p.x, p.y] : [p.x, p.y, cx, cy];
        const k = 26 / Math.hypot(x2 - x1, y2 - y1);
        return <line key={i} x1={x1.toFixed(1)} y1={y1.toFixed(1)} x2={(x2 - (x2 - x1) * k).toFixed(1)} y2={(y2 - (y2 - y1) * k).toFixed(1)} markerEnd="url(#harrow)"><title>{e.rel}</title></line>;
      })}</g>
      <circle cx={cx} cy={cy} r={16} className={css.center} />
      <Label ls={cl} x={cx} y={cy + 34} anchor="middle" />
      {pos.map(p => {
        const c = Math.cos(p.a), s = Math.sin(p.a), label = name(p.nd);
        const anchor = Math.abs(c) < .08 ? "middle" : c > 0 ? "start" : "end" as const;   // 정확히 위·아래만 가운데 — 이웃 라벨과 겹치지 않게
        const lx = p.x + (anchor === "middle" ? 0 : c > 0 ? 16 : -16), ly = p.y + (anchor === "middle" ? (s > 0 ? 30 : -30) : 4);
        const ls = lines(label, narrow), ty = anchor === "middle" && s < 0 ? ly - (ls.length - 1) * 14 : ly;
        const body = <><circle cx={p.x.toFixed(1)} cy={p.y.toFixed(1)} r={10} className={css[`k-${p.nd.kind}`]} /><Label ls={ls} x={lx} y={ty} anchor={anchor} /><title>{`${p.nd.kindName}, ${label}`}</title></>;
        return p.nd.href
          ? <a key={p.nd.key} href={p.nd.href} className={css.node} aria-label={`${p.nd.kindName} ${label}`}>{body}</a>
          : <g key={p.nd.key} className={css.node}>{body}</g>;
      })}
    </svg>
  );
}
