// 종류별 건수 — 주색 한 색 막대(범례 없음 — 제목이 이름). 숫자는 글자로, 막대는 꾸밈(aria-hidden). 종류 이름은 그 탭 링크
import { Wait } from "./Wait";
import { Blk } from "./Blk";
import type { BlockProps } from "./block";
import css from "./Summary.module.css";

const KINDS: [string, string, string][] = [["principle", "기준", "#_me/principle"], ["decision", "결정", "#_me/decision"], ["axis", "축", "#_me/axis"],
  ["custom", "커스텀", "#_me/custom"], ["records", "내 글", ""], ["readings", "읽기 자료", ""], ["people", "사람", "#_me/person"], ["sources", "출처", "#_me/source"]];
const LOCK = new Set(["principle", "decision", "axis", "people", "sources"]);
const TITLE = "종류별 건수";

export function Kinds({ W, statsFail }: BlockProps) {
  const k = W.stats?.kinds;
  if (!k) return <Blk title={TITLE}><Wait fail={statsFail} /></Blk>;
  const max = KINDS.reduce((m, [key]) => Math.max(m, k[key] || 0), 0);
  return (
    <Blk title={TITLE}>
      <ul className={css.kinds}>{KINDS.map(([key, label, href]) => {
        const n = k[key] || 0, lab = <>{label}{LOCK.has(key) && <> <span className="lk" aria-label="표준">🔒</span></>}</>;
        return (
          <li key={key} className={n ? "" : css.zero}>
            {href ? <a href={href}>{lab}</a> : <span>{lab}</span>}
            <span className={css.bar} aria-hidden="true">{n ? <i style={{ width: `${(n / max * 100).toFixed(2)}%` }} /> : null}</span><b>{n}</b>
          </li>
        );
      })}</ul>
    </Blk>
  );
}
