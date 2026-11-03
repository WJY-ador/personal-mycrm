// 출처 목록 + 저장(옛 renderSources · source-new) — 같은 종류·이름·위치면 서버가 그 출처를 돌려준다(그 출처를 연다)
import type { FormEvent } from "react";
import { Crumbs } from "../../shared/Crumbs";
import { srcName } from "./model";
import { objApi } from "./objApi";
import type { P } from "./props";
import { HOME, SRC_KIND } from "./text";
import { useWrite } from "./useWrite";
import css from "./Objects.module.css";

export function Sources({ ctx, S, msg }: P) {
  const w = useWrite(ctx), srcs = S.sources || [], by = S.source_counts?.by_source || {};
  async function add(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = e.currentTarget, d = new FormData(f), body = { kind: String(d.get("kind") || ""), name: String(d.get("name") || ""), location: String(d.get("location") || "") };
    if (!body.name.trim()) return w.setErr("new", "출처 이름을 적어 주세요.");
    if (await w.go("new", () => objApi.sourceNew(body), j => ["출처를 저장했어요.", j?.id ? `#_obj/source/${j.id}` : "#_obj/source"])) f.reset();
  }
  return (
    <div className="paper sheet"><Crumbs xs={[HOME, ["", "출처"]]} />{msg}<h2 className="title">출처 <span className="count">{srcs.length}</span></h2>
      <form className="fform" noValidate onSubmit={add}>
        <fieldset><legend>종류</legend>{Object.entries(SRC_KIND).map(([k, l], i) => <label key={k}><input type="radio" name="kind" value={k} defaultChecked={i === 0} /> {l}</label>)}</fieldset>
        <label htmlFor="source-new-name">이름</label><input className="finput" id="source-new-name" name="name" type="text" autoComplete="off" />
        <label htmlFor="source-new-loc">위치 <span className="tech">선택 — 파일 경로·웹 주소</span></label><input className="finput" id="source-new-loc" name="location" type="text" autoComplete="off" />
        <p className="hint">같은 종류·이름·위치의 출처가 이미 있으면 그 출처를 열어요.</p>
        <div className="frow"><button className="primary" type="submit" disabled={w.busy}>출처 저장</button></div>
        <p className="ferr" role="alert" aria-atomic="true">{w.errOf("new")}</p></form>
      <section className="sec">{srcs.length ? <div className="cards">{srcs.map(x => {
        const rn = (S.reflections || []).filter(r => r.source_id === x.id).length;
        return <div key={x.id} className={`card ${css.pcard}`}><a href={`#_obj/source/${x.id}`}>{srcName(S, x.id)}</a><span className="tech">글 {by[x.id] || 0} · 읽고 든 생각 {rn}</span></div>;
      })}</div> : <div className="empty">아직 출처가 없어요.</div>}</section>
    </div>
  );
}
