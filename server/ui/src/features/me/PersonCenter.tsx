// 사람 가운데 — 별칭 · 추가 시각 · 고치기 링크 + 관계 렌즈 그래프(문맥 API: 이 사람의 활동·글, 이 사람을 가리키는 항목)
import { mdhm } from "../../shared/date";
import type { Person } from "../../shared/state";
import { ConnGraph } from "./ConnGraph";
import { edges, node } from "./links";
import type { World } from "./model";
import { CONN_FAIL, LOADING, ME_LENS } from "./text";
import css from "./Me.module.css";

type Props = { W: World; p: Person; state: "ok" | "loading" | "fail"; retry: () => void };

export function PersonCenter({ W, p, state, retry }: Props) {
  const c = W.personCtx[p.id];
  return (
    <>
      <div className={css.kind}>사람<span className={`chip ${css.lensChip}`}>{ME_LENS.person}</span></div>
      <h2 className="title">{p.alias}</h2>
      <p className="recmeta">{mdhm(p.created)} 추가 · <a href={`#_obj/person/${p.id}`}>별칭 고치기·삭제</a></p>
      {state === "loading" ? <p className="hint">{LOADING}</p>
        : state === "fail" ? <div className="empty">{CONN_FAIL} <button className="tertiary" type="button" onClick={retry}>다시 시도</button></div>
        : <ConnGraph W={W} center={node(W, "person", p.id)} all={edges(W, "person", p.id)} hidden={c ? c.activity_count - c.activities.length : 0} omitHint="옆 목록에서 전부 볼 수 있어요." />}
    </>
  );
}
