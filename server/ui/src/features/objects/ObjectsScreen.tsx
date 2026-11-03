// 「자료 종류」 화면(옛 renderObjects·renderPeople·renderPerson·renderSources·renderSource·renderRefls·renderReflNew·renderRefl) —
// #_obj · #_obj/person[/<id>] · #_obj/source[/<id>] · #_obj/reflection[/<id>|/new[/<출처 id>]] (Setup 안이면 #_setup/objects/…). ctx.args = [a, b, c].
// 활동·축(#_obj/activity·axis)은 껍데기가 「활동」 화면으로 띄운다. 쓰기 = 폼·버튼(옛 coreSubmit·coreAct 경로 그대로) + 별칭 클릭 편집(shared Editable).
import type { ScreenProps } from "../../shared/ctx";
import { EditCtx, useEditStore } from "../../shared/edit";
import { Index } from "./Index";
import { People } from "./People";
import { Person } from "./Person";
import { Refl } from "./Refl";
import { ReflNew, Refls } from "./Refls";
import { Source } from "./Source";
import { Sources } from "./Sources";

export function ObjectsScreen({ ctx }: ScreenProps) {
  const edit = useEditStore(ctx);
  const S = ctx.state!, [a = "", b = "", c = ""] = ctx.args || [];
  const msg = <p className={edit.flash?.bad ? "fok bad" : "fok"} id="core-msg" role="status" aria-atomic="true">{edit.flash?.text}</p>;
  const p = { ctx, S, msg };
  let body;
  if (a === "person") body = b ? <Person key={b} {...p} id={b} /> : <People {...p} />;
  else if (a === "source") body = b ? <Source key={b} {...p} id={b} /> : <Sources {...p} />;
  else if (a === "reflection") body = b === "new" ? <ReflNew {...p} sid={c} /> : b ? <Refl key={b} {...p} id={b} /> : <Refls {...p} />;
  else body = <Index {...p} />;
  return <EditCtx.Provider value={edit}>{body}</EditCtx.Provider>;
}
