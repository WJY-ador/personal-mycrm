// 그래프 + 생략 표시 + 종류 거르기(넘칠 때만). 거르기는 읽기만(쓰기 요청 없음)
import { capped, kindName, type Edge, type GNode } from "./links";
import { Graph } from "./Graph";
import { useNames } from "./useNames";
import type { World } from "./model";
import { useMobile, useView } from "./view";
import { NO_CONN } from "./text";
import css from "./Me.module.css";

type Props = { W: World; center: GNode; all: Edge[]; hidden?: number; omitHint: string };

export function ConnGraph({ W, center, all, hidden = 0, omitHint }: Props) {
  const narrow = useMobile(), v = useView();
  const c = capped(all, narrow, v.kind, hidden);
  const name = useNames(W, [center, ...c.nodes]);
  if (!all.length && !hidden) return <div className="empty">{NO_CONN}</div>;
  return (
    <>
      <Graph center={center} nodes={c.nodes} edges={c.edges} narrow={narrow} name={name} />
      {(c.omitN > 0 || c.omitE > 0) && <p className="hint">{`데이터 ${c.omitN}개와 연결 ${c.omitE}개를 생략했어요. ${omitHint}`}</p>}
      {c.filter && (
        <div className={css.connf}>
          <label className="sr" htmlFor="conn-kind">연결 종류</label>
          <select id="conn-kind" value={c.kind} onChange={e => v.setKind(e.target.value)}>
            <option value="">전체 종류</option>
            {c.kinds.map(k => <option key={k} value={k}>{kindName(null, k)}</option>)}
          </select>
        </div>
      )}
    </>
  );
}
