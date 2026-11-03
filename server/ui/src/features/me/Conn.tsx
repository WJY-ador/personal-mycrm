// 상세의 「연결」 — 중심 1 + 직접 이웃(저장된 관계만). 그래프 ↔ 목록 전환. lens 가 있으면(기준·결정·축 탭) 그래프만 + 렌즈 이름(목록은 옆 묶음).
// 축 항목이면 그 축에 이어진 활동을 기존 문맥 API 로 받아 같이 그린다(받는 중 = 불러오는 중, 실패 = 다시 시도).
import { useQuery } from "@tanstack/react-query";
import { edges, node } from "./links";
import { ConnGraph } from "./ConnGraph";
import { ConnList } from "./ConnList";
import { defById, itemById, type World } from "./model";
import { axisCtx, QK } from "./useWorld";
import { CONN_FAIL, LOADING, NO_CONN } from "./text";
import { useView } from "./view";
import css from "./Me.module.css";

export const isAxis = (W: World, id: string) => { const it = itemById(W, id); return !!(it && defById(W, it.object_id)?.key === "axes"); };

export function Conn({ W, kind, id, lens }: { W: World; kind: string; id: string; lens?: string }) {
  const v = useView();
  const axis = kind === "item" && isAxis(W, id);
  const q = useQuery({ queryKey: QK.axis(id), queryFn: () => axisCtx(id), enabled: axis });
  const all = edges(W, kind, id), center = node(W, kind, id);
  const hidden = q.data ? Math.max(0, q.data.activity_count - q.data.activities.length) : 0;
  const fail = axis && q.isError
    ? <div className="empty">{CONN_FAIL} <button className="tertiary" type="button" onClick={() => void q.refetch()}>다시 시도</button></div> : null;
  const pending = axis && q.isPending && !q.isError;
  let body;
  if (lens) body = pending ? <p className="hint">{LOADING}</p> : <><ConnGraph W={W} center={center} all={all} hidden={hidden} omitHint="옆 목록에서 전부 볼 수 있어요." />{fail}</>;
  else if (!all.length) body = fail || (pending ? <p className="hint">{LOADING}</p> : <div className="empty">{NO_CONN}</div>);
  else body = <>{v.mode === "list" ? <ConnList W={W} all={all} /> : <ConnGraph W={W} center={center} all={all} hidden={hidden} omitHint="목록으로 보면 전부 보여요." />}{fail}</>;
  return (
    <section className={css.conn} aria-labelledby="hconn-h">
      <div className="sechead">
        <h3 id="hconn-h">연결</h3>
        {lens ? <span className={`chip ${css.lensChip}`}>{lens}</span>
          : all.length > 0 && <button className="secondary" type="button" onClick={v.toggle}>{v.mode === "graph" ? "목록으로 보기" : "그래프로 보기"}</button>}
      </div>
      {body}
    </section>
  );
}
