// 축 띠 — 축별 연결 건수 비율(서버 통계) + 칩(색·코드·이름·건수 — 색만으로 구분하지 않음). 축 색 = 코드 순 1~8, 9번째부터 회색
import { axColor, axShort, axTip, axes, type World } from "./model";
import { STATS_FAIL } from "./text";
import css from "./Me.module.css";

export function AxisBand({ W, sel, fail }: { W: World; sel: string; fail: boolean }) {
  const ax = axes(W);
  if (!ax.length) return null;
  if (!W.stats) return (
    <section className={css.axis} aria-label="축별 연결 건수">
      <div className={css.axrow}><span className={css.axl}>축</span><div className={`${css.strip} ${css.none}`} /></div>
      {fail && <p className={`hint ${css.fail}`} role="status">{STATS_FAIL}</p>}
    </section>
  );
  const tot = ax.reduce((s, a) => s + (a.n || 0), 0);
  return (
    <section className={css.axis} aria-label="축별 연결 건수">
      <div className={css.axrow}><span className={css.axl}>축</span>
        <div className={`${css.strip}${tot ? "" : " " + css.none}`} role="img" aria-label={`축별 연결 비율 · 합 ${tot}`}>
          {tot ? ax.map((a, i) => (a.n ? <span key={a.id} style={{ flex: `${a.n} 1 0`, background: axColor(i) }} title={axTip(a)} /> : null)) : null}
        </div></div>
      <div className={css.chips}>{ax.map((a, i) => (
        <a key={a.id} href={`#_me/axis/${a.id}`} className={a.n ? undefined : css.zero} aria-current={a.id === sel ? "true" : undefined} title={axTip(a)} aria-label={`축 ${axTip(a)}`}>
          <i style={{ background: axColor(i) }} />{a.code && <b>{a.code}</b>}<span className={css.axt}>{axShort(a.title)}</span><span className={css.v}>{a.n || 0}</span>
        </a>
      ))}</div>
    </section>
  );
}
