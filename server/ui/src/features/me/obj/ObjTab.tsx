// 오브젝트 탭(#_me/obj/<key>[/<항목 id>]) — Salesforce Custom Tab 꼴: 목록 보기(List View) 또는 항목 페이지(Record Page) 하나.
// 정렬·필터·검색은 이 탭에 머무는 동안만 기억한다(항목 페이지에 갔다 와도 그대로, 저장 없음). 항목 페이지 = 기존 항목 상세(필드 전부).
import { useState } from "react";
import type { Def } from "../../../shared/state";
import { Back } from "../Back";
import { Detail } from "../Detail";
import type { ObjQuery } from "../meApi";
import { homeRows, type World } from "../model";
import { GONE, OBJ_TEXT } from "../text";
import { useMobile } from "../view";
import { ObjList } from "./ObjList";
import css from "../Me.module.css";

export const objHref = (key: string, id = "") => `#_me/obj/${encodeURIComponent(key)}${id ? "/" + encodeURIComponent(id) : ""}`;
export const NO_QUERY: ObjQuery = { sort: "", dir: "", q: "", f: {}, state: "" };

export function ObjTab({ W, def, id, trashOn }: { W: World; def: Def; id: string; trashOn: boolean }) {
  const [vq, setVq] = useState<ObjQuery>(NO_QUERY);
  const mobile = useMobile();
  if (!id) return <ObjList W={W} def={def} vq={vq} setVq={setVq} />;
  const r = homeRows(W).find(x => x.k === "item" && x.id === id);
  const list = objHref(def.key);
  return (
    <section className={`paper hdetail ${css.solo}`} id="home-detail" aria-live="polite">
      {mobile ? <Back to={list} label={OBJ_TEXT.back} /> : <p className="hback"><a href={list}>{def.label} {OBJ_TEXT.back}</a></p>}
      {r && r.k === "item" && r.x.object_id === def.id ? <Detail W={W} r={r} trashOn={trashOn} />
        : <div className="empty">{GONE} <a href={list}>{OBJ_TEXT.back}</a></div>}
    </section>
  );
}
