// 사람 목록 + 추가(옛 renderPeople · person-new) — 별칭 하나만 저장한다(연락처·소속·SNS·그 사람의 말·평가 칸 없음, 서버 규칙 그대로)
import type { FormEvent } from "react";
import { Crumbs } from "../../shared/Crumbs";
import { md } from "../../shared/date";
import { objApi } from "./objApi";
import type { P } from "./props";
import { HOME, PERSON_HELP } from "./text";
import { useWrite } from "./useWrite";
import css from "./Objects.module.css";

export function People({ ctx, S, msg }: P) {
  const w = useWrite(ctx), ps = S.people || [];
  async function add(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = e.currentTarget, alias = String(new FormData(f).get("alias") || "");
    if (!alias.trim()) return w.setErr("new", "별칭을 적어 주세요.");
    if (await w.go("new", () => objApi.personNew(alias), () => ["사람을 추가했어요.", "#_obj/person"])) f.reset();
  }
  return (
    <div className="paper sheet"><Crumbs xs={[HOME, ["", "사람"]]} />{msg}<h2 className="title">사람 <span className="count">{ps.length}</span></h2>
      <form className="fform" noValidate onSubmit={add}>
        <label htmlFor="person-new-alias">별칭</label>
        <div className="frow" style={{ margin: 0 }}><input className="finput" id="person-new-alias" name="alias" type="text" autoComplete="off" aria-describedby="person-new-help" style={{ flex: "1 1 14rem" }} />
          <button className="primary" type="submit" disabled={w.busy}>추가</button></div>
        <p className="hint" id="person-new-help">{PERSON_HELP} 연락처·소속·SNS·그 사람의 말·평가는 적지 않아요.</p>
        <p className="ferr" role="alert" aria-atomic="true">{w.errOf("new")}</p></form>
      <section className="sec">{ps.length ? <div className="cards">{ps.map(p => <div key={p.id} className={`card ${css.pcard}`}><a href={`#_obj/person/${p.id}`}>{p.alias}</a><span className="tech">{md(p.created)} 추가</span></div>)}</div>
        : <div className="empty">아직 사람이 없어요.</div>}</section>
    </div>
  );
}
