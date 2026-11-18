// 「오늘」 머리 「오늘의 축」(축 잇기, 2026-11-18 명세 4.2 — 대시보드.app 오늘의 축 막대와 같은 꼴) — 축별 대기 수 비율 한 줄 막대 + 아래 축 목록(코드, 이름, 수).
// 누르면 그 축 화면(#_me/axis/<축 item id>). 대기 0 축은 숨긴다. 축이 없거나 대기 합이 0이면 막대를 그리지 않는다.
// 색 = 축 전체 순서의 번호(--ax1~8, 대기 0 을 숨겨도 색이 밀리지 않는다). 못 불러오면 한 줄만.
import { axColor, axisHref, useAxes } from "../../shared/axes";
import css from "./TodayAxes.module.css";

export function TodayAxes() {
  const q = useAxes();
  if (q.isError) return <p className={`hint ${css.fail}`} role="status">오늘의 축을 불러오지 못했어요. 새로 고침해 주세요.</p>;
  const shown = (q.data?.axes || []).map((a, i) => ({ a, i })).filter(x => x.a.pending > 0);
  const tot = shown.reduce((s, x) => s + x.a.pending, 0);
  if (!tot) return null;
  return (
    <section className={css.box} aria-labelledby="today-axes-h" id="today-axes">
      <div className={css.row}><h3 id="today-axes-h" className={css.l}>오늘의 축</h3>
        <div className={css.strip} role="img" aria-label={`축별 대기 비율, 합 ${tot}`}>
          {shown.map(({ a, i }) => <span key={a.item_id} style={{ flex: `${a.pending} 1 0`, background: axColor(i) }} title={`${a.code} ${a.title} ${a.pending}`} />)}
        </div><span className={css.tot}>대기 {tot}</span></div>
      <ul className={css.list}>{shown.map(({ a, i }) => <li key={a.item_id}><a href={axisHref(a.item_id)} title={a.title}>
        <i style={{ background: axColor(i) }} /><b>{a.code}</b><span className={css.t}>{a.title}</span><span className={css.v}>{a.pending}</span></a></li>)}</ul>
    </section>
  );
}
