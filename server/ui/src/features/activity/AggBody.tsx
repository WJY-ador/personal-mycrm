// 활동 현황 본문(옛 aggHtml) — 서버 activity.me_aggregate 그대로 그린다(여기서 다시 세지 않는다). 성향 점수·친밀도는 그리지 않는다.
import type { Agg } from "../../shared/activity";
import { actLabel } from "../../shared/activity";
import { Bars } from "../../shared/Bars";
import { dOnly } from "../../shared/date";
import { josa } from "../../shared/LoadFail";
import type { AppState } from "../../shared/state";
import { QHelp } from "./QHelp";
import { HELP } from "./text";
import css from "./Activity.module.css";

export function AggBody({ g, S }: { g: Agg; S: AppState }) {
  const ui = S.activity_ui;
  const range = g.from ? `${dOnly(g.from)} ~ ${dOnly(g.to)} (오늘 포함, 한국 시간)` : `${dOnly(g.to)}까지 전체`;
  const und = g.undated || { n: 0, observed: [] };
  const acts = (g.by_action || []).map(x => ({ label: x.label || actLabel(ui?.actions, x.action), n: x.n, href: `#_obj/activity/list/action=${x.action}` }));
  const axes = (g.by_axis || []).map(x => ({ label: x.title || "(제목 없음)", n: x.n, href: `#_obj/axis/${x.item_id}` }));
  if (g.axis_unclassified) axes.push({ label: "축 미분류", n: g.axis_unclassified, href: "" });
  const ppl = (g.top_people || []).map(x => ({ label: x.alias, n: x.n, href: `#_obj/person/${x.person_id}` }));
  const srcs = (g.by_source || []).map(x => ({ label: x.provider ? `${x.name}, ${ui?.providers?.[x.provider] || x.provider}` : x.name, n: x.n, href: `#_obj/source/${x.source_id}` }));
  const obs = (und.observed || []).map(x => ({ label: x.observed_on ? dOnly(x.observed_on) : "기록 없음", n: x.n }));
  const prs = (g.grounds || { principles: [] }).principles || [];
  const rule = (S.definitions || []).find(d => d.semantic_kind === "principle")?.label || "기준";
  const items = S.items || [];
  return (
    <>
      <p className={`recmeta ${css.range}`}>{range}, 행동 날짜가 확인된 활동만 기간에 넣어요</p>
      <div className={css.stats}><div className={css.stat}><b>{g.total}</b><span>활동</span></div>
        <a className={css.stat} href="#_obj/activity/list/dated=no"><b>{und.n}</b><span>날짜 미확인, 기간 밖</span></a>
        <div className={css.stat}><b>{g.axis_unclassified || 0}</b><span>축 미분류</span></div></div>
      <div className={css.cols}>
        <section><h2 className="sh">행동별</h2><Bars rows={acts} empty="이 기간엔 활동이 없어요." /></section>
        <section><h2 className="sh">축별{g.axis_sum_differs ? <QHelp t={HELP.axisSum} /> : null}</h2><Bars rows={axes} empty="이 기간엔 활동이 없어요." /></section>
        <section><h2 className="sh">자주 반응한 사람<QHelp t={HELP.people} /></h2><Bars rows={ppl} empty="아직 없어요." /></section>
        <section><h2 className="sh">출처 구성</h2><Bars rows={srcs} empty="이 기간엔 활동이 없어요." /></section>
      </div>
      <div className={`${css.cols} ${css.two}`}>
        <section><h2 className="sh">날짜 미확인 <span className="speclabel">{und.n}</span><QHelp t={HELP.undated} /></h2>
          {und.n ? <Bars rows={obs} empty="" /> : <div className="empty">없어요.</div>}</section>
        <section><h2 className="sh">연결된 판단과 기준<QHelp t={HELP.grounds(rule)} /></h2>
          {prs.length ? <ul className="mini">{prs.map(p => {
            const it = items.find(i => i.id === p.item_id);
            return <li key={p.item_id}>{it ? <a href={`#structure/${it.object_id}/${it.id}`}>{p.title || "(제목 없음)"}</a> : p.title || "(제목 없음)"}
              <span className="tech">글 {p.records}, 활동 {p.activities}</span></li>;
          })}</ul> : <div className="empty">{`연결된 ${rule}${josa(rule, "이", "가")} 없어요.`}</div>}</section>
      </div>
    </>
  );
}
