// 13주 글·활동 — 날짜 칸(주색 한 색 농도 5단, 0 = 빈 칸) · 미래 칸 비움 · 하루 최대 = 가장 진한 칸. 칸마다 <title> 날짜·건수
import { dOnly } from "../../../shared/date";
import { Wait } from "./Wait";
import { Blk } from "./Blk";
import { today, type BlockProps } from "./block";
import css from "./Summary.module.css";

const TITLE = "13주 글·활동";

export function Heatmap({ W, statsFail }: BlockProps) {
  const h = W.stats?.heatmap;
  if (!h || !Array.isArray(h.cells) || !h.cells.length) return <Blk title={TITLE}><Wait fail={statsFail} /></Blk>;
  const t = today(), cells = h.cells.map((c, i) => ({ ...c, w: Math.floor(i / 7), dw: i % 7, n: (c.records || 0) + (c.activities || 0), future: c.d > t }));
  const past = cells.filter(c => !c.future), max = past.reduce((m, c) => Math.max(m, c.n), 0), sum = past.reduce((s, c) => s + c.n, 0);
  const sumR = past.reduce((s, c) => s + (c.records || 0), 0), sumA = past.reduce((s, c) => s + (c.activities || 0), 0);
  const lvl = (n: number) => (n <= 0 ? 0 : Math.min(4, Math.ceil(4 * n / max)));
  const C = 14, G = 3, P = C + G, L = 22, T = 16, RM = 12, Wd = L + 13 * P + RM, H = T + 7 * P;   // RM = 마지막 달 라벨(「11월」) 오른쪽 여백
  const months: [number, number][] = [];
  let pm = "";
  for (let w = 0; w < 13; w++) { const c = cells[w * 7]; if (!c) continue; const mo = c.d.slice(5, 7); if (mo !== pm) { months.push([w, +mo]); pm = mo; } }
  if (months.length > 1 && months[1][0] - months[0][0] < 2) months.shift();   // 첫 달이 1주뿐이면 라벨이 겹친다
  return (
    <Blk title={TITLE} meta={`${sum} · ${dOnly(h.from)}–${dOnly(t)}`}>
      <svg className={css.heat} viewBox={`0 0 ${Wd} ${H}`} role="img" aria-label={`13주 날짜별 글·활동 · 합 ${sum}(글 ${sumR} · 활동 ${sumA}) · 하루 최대 ${max}`}>
        {months.map(([w, m]) => <text key={w} x={L + w * P} y={12}>{m}월</text>)}
        {([[0, "월"], [2, "수"], [4, "금"]] as const).map(([d, s]) => <text key={d} x={0} y={T + d * P + 11}>{s}</text>)}
        {past.map(c => <rect key={c.d} className={css[`h${lvl(c.n)}`]} x={L + c.w * P} y={T + c.dw * P} width={C} height={C} rx={3}><title>{`${dOnly(c.d)} · 글 ${c.records || 0} · 활동 ${c.activities || 0}`}</title></rect>)}
      </svg>
      {sum ? <p className={css.legend}><span>적음</span>{[0, 1, 2, 3, 4].map(i => <i key={i} className={css[`h${i}`]} />)}<span>많음</span><span className={css.sep}>{`하루 최대 ${max}`}</span></p>
        : <p className="hint">이 기간에 날짜가 있는 글·활동이 없어요.</p>}
    </Blk>
  );
}
