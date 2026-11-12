// 사람 하나(옛 renderPerson) — 별칭(누르면 인라인 편집, 상시 연필) · [삭제](휴지통 켜짐 = 휴지통, 꺼짐 = 즉시 삭제) · 연결된 활동·글·항목(문맥 API)
import { Crumbs } from "../../shared/Crumbs";
import { mdhm } from "../../shared/date";
import { useEdit } from "../../shared/edit";
import { Editable } from "../../shared/Editable";
import { Editor } from "../../shared/Editor";
import { postMsg } from "../../shared/postErr";
import { trashOn } from "./model";
import { objApi } from "./objApi";
import { PersonCtx } from "./PersonCtx";
import type { P } from "./props";
import { HOME, PERSON_HELP, TRASH_ASK, TRASH_DONE } from "./text";
import { useWrite } from "./useWrite";
import css from "./Objects.module.css";

export function Person({ ctx, S, msg, id }: P & { id: string }) {
  const { editing, act } = useEdit(), w = useWrite(ctx);
  const p = (S.people || []).find(x => x.id === id), on = trashOn(S);
  if (!p) return <div className="paper sheet"><Crumbs xs={[HOME, ["#_obj/person", "사람"]]} />{msg}<div className="empty">찾을 수 없는 사람이에요. 지워졌을 수 있어요.</div></div>;
  const key = "alias:" + p.id;
  const spec = { key, done: "별칭을 고쳤어요.", errText: postMsg,
    fields: [{ name: "alias", label: "별칭", multi: false, orig: p.alias }], save: (d: Record<string, string>) => objApi.personEdit(p.id, d.alias, p.revision) };
  function del() {
    if (on) { if (window.confirm(TRASH_ASK)) void w.go("act", () => objApi.trash("person", p!.id, p!.revision), () => [TRASH_DONE, "#_obj/person"]); }
    else if (window.confirm("이 사람을 지울까요? 되돌릴 수 없어요.")) void w.go("act", () => objApi.personDel(p!.id, p!.revision), () => ["사람을 지웠어요.", "#_obj/person"]);
  }
  return (
    <>
      <div className="paper sheet"><Crumbs xs={[HOME, ["#_obj/person", "사람"], ["", p.alias]]} />{msg}
        <div className="eyebrow">사람</div>
        {editing(key) ? <Editor /> : <h2 className={`title ${css.alias}`}><Editable spec={spec} look="name">{p.alias}</Editable></h2>}
        <p className="recmeta">{mdhm(p.created)} 추가, {mdhm(p.updated)} 고침</p>
        <p className="hint">{PERSON_HELP}</p>
        {editing(key) ? null : <div className="frow"><button className="secondary" type="button" disabled={w.busy} onClick={del}>삭제</button></div>}
        <p className="ferr" role="alert" aria-atomic="true">{w.errOf("act")}</p>
        <p className="fok" role="status" aria-atomic="true">{act?.ok}</p>
      </div>
      <div className="paper sheet"><PersonCtx S={S} id={p.id} /></div>
    </>
  );
}
