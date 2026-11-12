// 읽고 든 생각 하나(옛 renderRefl) — 확인 상태·유형·출처 · 시각·판 · 본문 · [확인했어요|확인 전으로] · [삭제](휴지통 켜짐 = 휴지통, 꺼짐 = 즉시 삭제) · 고치기 폼
import { Crumbs } from "../../shared/Crumbs";
import { mdhm } from "../../shared/date";
import { rich } from "../../shared/rich";
import { srcName, trashOn } from "./model";
import { objApi } from "./objApi";
import type { P } from "./props";
import { Badge, ReviewBtn } from "./ReflCard";
import { ReflForm } from "./ReflForm";
import { HOME, REFL_KIND, REVIEW_NOTE, TRASH_ASK, TRASH_DONE } from "./text";
import { useWrite } from "./useWrite";
import css from "./Objects.module.css";

export function Refl(p: P & { id: string }) {
  const { ctx, S, msg, id } = p, w = useWrite(ctx);
  const x = (S.reflections || []).find(r => r.id === id);
  if (!x) return <div className="paper sheet"><Crumbs xs={[HOME, ["#_obj/reflection", "읽고 든 생각"]]} />{msg}<div className="empty">찾을 수 없는 읽고 든 생각이에요. 지워졌을 수 있어요.</div></div>;
  const back = `#_obj/source/${x.source_id}`;
  function del() {
    if (trashOn(S)) { if (window.confirm(TRASH_ASK)) void w.go("act", () => objApi.trash("reflection", x!.id, x!.revision), () => [TRASH_DONE, back]); }
    else if (window.confirm("이 읽고 든 생각을 지울까요? 되돌릴 수 없어요.")) void w.go("act", () => objApi.reflDel(x!.id, x!.revision), () => ["읽고 든 생각을 지웠어요.", back]);
  }
  return (
    <>
      <div className="paper sheet"><Crumbs xs={[HOME, ["#_obj/reflection", "읽고 든 생각"], ["", REFL_KIND[x.kind] || x.kind]]} />{msg}
        <div className="labels"><Badge x={x} /><span className="chip">{REFL_KIND[x.kind] || x.kind}</span><a className="chip src" href={`#_obj/source/${x.source_id}`}>{srcName(S, x.source_id)}</a></div>
        <p className="recmeta" style={{ margin: ".3rem 0 .6rem" }}>{mdhm(x.created)} 씀, {mdhm(x.updated)} 고침{x.reviewed_at ? `, ${mdhm(x.reviewed_at)} 확인했어요` : ""}</p>
        <div className="doc"><p>{rich(x.body)}</p></div>
        <div className={css.pacts} style={{ margin: ".7rem 0 0" }}><ReviewBtn x={x} w={w} k="act" />
          <button className="secondary" type="button" disabled={w.busy} onClick={del}>삭제</button></div>
        <p className="hint" style={{ margin: ".4rem 0 0" }}>{REVIEW_NOTE}</p>
        <p className="ferr" role="alert" aria-atomic="true">{w.errOf("act")}</p></div>
      <div className="paper sheet"><h2 className="sh">고치기</h2><ReflForm {...p} x={x} /></div>
    </>
  );
}
