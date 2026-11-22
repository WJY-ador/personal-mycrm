// 한 장 본문 그리기 — 「# 」 머리를 떼고(dropH1) 사례 짝 짓기(cases.ts) 조각을 md() 와 접힌 사례(details), 라벨 | 내용 표로 그린다.
// 저장 본문은 바꾸지 않는다(그리기만). 편집 상자에는 원문 그대로가 간다(AxisEdit).
import type { Md } from "./AxisDoc";
import { dropH1 } from "./AxisDoc";
import { pairCases, type Case } from "./cases";
import { AXIS_TEXT as T } from "../text";
import css from "./Axis.module.css";

function CaseFold({ c, md, k }: { c: Case; md: Md; k: string }) {
  return (
    <details className={css.case}>
      <summary><span className={css.cl}>{T.caseMark}</span>{c.title}</summary>
      {c.rows.length ? <table className={css.ct}><tbody>{c.rows.map((r, i) =>
        <tr key={i}><th scope="row">{r.label}</th><td>{md(r.text, `${k}-r${i}`)}</td></tr>)}</tbody></table> : null}
      {c.rest ? <div className={css.cr}>{md(c.rest, k + "-rest")}</div> : null}
    </details>
  );
}

export function AxisBody({ markdown, md, k }: { markdown: string; md: Md; k: string }) {
  const segs = pairCases(dropH1(markdown));
  return <>{segs.map((s, i) => s.k === "md"
    ? <div key={i} className={css.seg}>{md(s.text, `${k}-${i}`)}</div>
    : <div key={i} className={css.cases}>{s.items.map((c, j) => <CaseFold key={j} c={c} md={md} k={`${k}-${i}-${j}`} />)}</div>)}</>;
}
