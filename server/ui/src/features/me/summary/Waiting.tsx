// 기다리는 결정 — 3 칸 띠 + 칸마다 글자 범례(색만으로 구분하지 않음). 범례 이름은 그 목록 링크
import { Wait } from "./Wait";
import { Blk } from "./Blk";
import type { BlockProps } from "./block";
import css from "./Summary.module.css";

const WAIT: [string, string, string, string][] = [["candidates_pending", "검토할 판단", "#structure/cand/pending", "w1"],
  ["principles_pending", "확정 전 기준", "#_me/principle", "w2"], ["inbox_pending", "저장 승인 대기", "#_today", "w3"]];
const TITLE = "기다리는 결정";

export function Waiting({ W, statsFail }: BlockProps) {
  const w = W.stats?.waiting;
  if (!w) return <Blk full title={TITLE}><Wait fail={statsFail} /></Blk>;
  const tot = WAIT.reduce((t, [key]) => t + (w[key] || 0), 0);
  return (
    <Blk full title={TITLE} meta={String(tot)}>
      {tot ? <div className={css.wband} role="img" aria-label={WAIT.map(([key, label]) => `${label} ${w[key] || 0}`).join(", ")}>
        {WAIT.map(([key, label, , c]) => (w[key] ? <span key={key} className={css[c]} style={{ flex: `${w[key]} 1 0` }} title={`${label} ${w[key]}`} /> : null))}
      </div> : <p className="hint">기다리는 결정이 없어요.</p>}
      <ul className={css.wlegend}>{WAIT.map(([key, label, href, c]) => (
        <li key={key} className={w[key] ? "" : css.zero}><i className={css[c]} /><a href={href}>{label}</a><b>{w[key] || 0}</b></li>
      ))}</ul>
    </Blk>
  );
}
