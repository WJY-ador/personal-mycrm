// 종류별 건수 — 주색 한 색 막대(범례 없음 — 제목이 이름). 숫자는 글자로, 막대는 꾸밈(aria-hidden). 종류 이름은 그 탭 링크.
// 사용자 오브젝트는 오브젝트마다 한 칸(건수 = 상태 S 의 적용·미보관 항목, 하위 탭 건수와 같은 값) — 그 오브젝트 탭으로 잇는다
import { Lock } from "../../../shared/Glyph";
import { customDefs, itemsOf } from "../model";
import { Wait } from "./Wait";
import { Blk } from "./Blk";
import type { BlockProps } from "./block";
import css from "./Summary.module.css";

type Row = { key: string; label: string; href: string; n: number; lock: boolean };
const HEAD: [string, string, string][] = [["principle", "기준", "#_me/principle"], ["decision", "결정", "#_me/decision"], ["axis", "축", "#_me/axis"]];
const TAIL: [string, string, string][] = [["records", "내 글", ""], ["readings", "읽기 자료", ""], ["people", "사람", "#_me/person"], ["sources", "출처", "#_me/source"]];
const LOCK = new Set(["principle", "decision", "axis", "people", "sources"]);
const TITLE = "종류별 건수";

export function Kinds({ W, statsFail }: BlockProps) {
  const k = W.stats?.kinds;
  if (!k) return <Blk title={TITLE}><Wait fail={statsFail} /></Blk>;
  const std = ([key, label, href]: [string, string, string]): Row => ({ key, label, href, n: k[key] || 0, lock: LOCK.has(key) });
  const rows: Row[] = [...HEAD.map(std),
    ...customDefs(W).map(d => ({ key: "obj:" + d.key, label: d.label, href: `#_me/obj/${encodeURIComponent(d.key)}`, n: itemsOf(W, d.id).length, lock: false })),
    ...TAIL.map(std)];
  const max = rows.reduce((m, r) => Math.max(m, r.n), 0);
  return (
    <Blk title={TITLE}>
      <ul className={css.kinds}>{rows.map(({ key, label, href, n, lock }) => {
        const lab = <>{label}{lock && <> <Lock /></>}</>;
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
