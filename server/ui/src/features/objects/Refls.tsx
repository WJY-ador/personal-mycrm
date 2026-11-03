// 읽고 든 생각 전체 목록(옛 renderRefls) · 새로 쓰기(옛 renderReflNew — #_obj/reflection/new[/<출처 id>], 출처를 미리 고른다)
import { Crumbs } from "../../shared/Crumbs";
import { srcById } from "./model";
import type { P } from "./props";
import { ReflCards } from "./ReflCard";
import { ReflForm } from "./ReflForm";
import { HOME, REFL_HELP } from "./text";

export function Refls(p: P) {
  const { S, msg } = p, rs = S.reflections || [];
  return (
    <div className="paper sheet"><Crumbs xs={[HOME, ["", "읽고 든 생각"]]} />{msg}
      <div className="sechead"><h2 className="title" style={{ margin: 0 }}>읽고 든 생각 <span className="count">{rs.length}</span></h2><a className="btn primary" href="#_obj/reflection/new">읽고 든 생각 쓰기</a></div>
      <p className="hint">{REFL_HELP} 「확인했어요」는 판단 확정이 아니에요.</p>
      {rs.length ? <ReflCards {...p} xs={rs} compact={false} /> : <div className="empty">아직 읽고 든 생각이 없어요.</div>}
    </div>
  );
}

export function ReflNew(p: P & { sid: string }) {
  return (
    <div className="paper sheet"><Crumbs xs={[HOME, ["#_obj/reflection", "읽고 든 생각"], ["", "쓰기"]]} />{p.msg}
      <h2 className="title">읽고 든 생각 쓰기</h2><ReflForm {...p} sid={srcById(p.S, p.sid) ? p.sid : ""} /></div>
  );
}
