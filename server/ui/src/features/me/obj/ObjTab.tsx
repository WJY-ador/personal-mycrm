// 오브젝트 탭(#_me/obj/<key>[/<항목 id>]) — Salesforce Custom Tab 꼴: 목록 보기(List View) 또는 항목 페이지(Record Page) 하나.
// 정렬·필터·검색은 이 탭에 머무는 동안만 기억한다(항목 페이지에 갔다 와도 그대로, 저장 없음). 항목 페이지 = 기존 항목 상세(필드 전부).
import { useEffect, useState } from "react";
import { hashPath, hashQuery, objFilterOf } from "../../../shared/route";
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
// 주소 쿼리(루틴판 숫자·축 칩 링크) → 목록 조건. 쿼리가 없으면 null(탭에 머무는 동안 기억한 조건 그대로)
const fromHash = (qs: string): ObjQuery | null => { if (!qs) return null; const F = objFilterOf(qs); return { ...NO_QUERY, ...F, state: F.state || "" }; };

// boardKey = 루틴판 한판 오브젝트 key(레이아웃 routine 블록 p.writing, 없으면 "") — 그 오브젝트 항목 페이지에만 「한판으로 보기」 링크 하나
export function ObjTab({ W, def, id, trashOn, boardKey = "" }: { W: World; def: Def; id: string; trashOn: boolean; boardKey?: string }) {
  const qs = hashQuery(location.hash);
  const [vq, setRaw] = useState<ObjQuery>(() => fromHash(qs) || NO_QUERY);
  // 목록 조건을 손으로 바꾸면 주소의 필터 쿼리를 뗀다(새로 고침·뒤로 가기가 옛 필터를 다시 걸지 않게). replaceState = 화면 이동, 맨 위로 없음
  const setVq = (q: ObjQuery) => {
    setRaw(q);
    if (hashQuery(location.hash)) history.replaceState(history.state, "", location.pathname + location.search + hashPath(location.hash));
  };
  useEffect(() => { const q = fromHash(qs); if (q) setRaw(q); }, [qs]);   // 같은 탭에서 다른 필터 링크로 왔을 때
  const mobile = useMobile();
  if (!id) return <ObjList W={W} def={def} vq={vq} setVq={setVq} />;
  const r = homeRows(W).find(x => x.k === "item" && x.id === id);
  const list = objHref(def.key), ok = !!r && r.k === "item" && r.x.object_id === def.id;
  return (
    <section className={`paper hdetail ${css.solo}`} id="home-detail" aria-live="polite">
      {mobile ? <Back to={list} label={OBJ_TEXT.back} /> : <p className="hback"><a href={list}>{def.label} {OBJ_TEXT.back}</a></p>}
      {ok && def.key === boardKey ? <p className="hint" id="board-link"><a href={`#_me/board/${encodeURIComponent(id)}`}>{OBJ_TEXT.board}</a></p> : null}
      {ok && r.k === "item" ? <Detail W={W} r={r} trashOn={trashOn} />
        : <div className="empty">{GONE} <a href={list}>{OBJ_TEXT.back}</a></div>}
    </section>
  );
}
