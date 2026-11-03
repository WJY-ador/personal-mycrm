// 이 출처의 활동 — 행동별 막대 + 최근 활동(문맥 API /api/sources/{id}/context). 받은 수보다 많으면 「모두 보기」
import { useQuery } from "@tanstack/react-query";
import { ActRows } from "./ActRows";
import { meApi } from "./meApi";
import type { World } from "./model";
import { LOADING } from "./text";

export function SourceActs({ W, sid }: { W: World; sid: string }) {
  const q = useQuery({ queryKey: ["me", "source", sid], queryFn: () => meApi.source(sid) });
  if (q.isError) return <div className="partfail" role="alert"><b>이 출처의 활동을 불러오지 못했어요 · 나머지는 정상</b></div>;
  if (!q.data) return <p className="hint">{LOADING}</p>;
  const j = q.data, max = j.by_action.reduce((m, r) => Math.max(m, r.n), 0);
  return (
    <>
      <div className="sechead"><h3>이 출처의 활동 <span className="speclabel">{j.activity_count}</span></h3></div>
      {!j.activity_count ? <div className="empty">이 출처의 활동이 없어요.</div> : <>
        <ul className="bars">{j.by_action.map(r => (
          <li key={r.action}><span>{r.label || r.action}</span>
            <span className="bar" aria-hidden="true"><i style={{ width: `${max ? Math.max(2, Math.round(r.n / max * 100)) : 0}%` }} /></span><b>{r.n}</b></li>
        ))}</ul>
        <ActRows W={W} xs={j.activities} />
        {j.activity_count > j.activities.length && <p className="hint">{`최근 ${j.activities.length}건만 보여요. `}<a href={`#_obj/activity/list/source=${encodeURIComponent(sid)}`}>모두 보기</a></p>}
      </>}
    </>
  );
}
