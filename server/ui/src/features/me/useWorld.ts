// 「나」 화면이 가진 것(World) — 상태 S(껍데기) + 이어 받은 기록 + 통계·레이아웃 + 문맥 API(축·사람). 서버 조회는 react-query 하나:
// 다시 받는 때 = 껍데기의 새 상태 알림(crm:state, main.tsx). 실패는 그대로 보이고 자동 재시도하지 않는다.
import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { apiErr } from "../../shared/api";
import { journalKey } from "../../shared/journal";
import type { AppState, Rec } from "../../shared/state";
import { meApi, type AxisCtx, type PersonCtx } from "./meApi";
import type { World } from "./model";
import { MORE_FAIL } from "./text";

export const QK = {
  stats: ["me", "stats"], layout: ["me", "layout"],
  axis: (id: string) => ["me", "axis", id], person: (id: string) => ["me", "person", id], journal: journalKey,
};

// 축이 아닌 항목 = NOT-FOUND → 활동 이웃 없음(실패 아님)
export const axisCtx = (id: string) => meApi.axis(id).catch(e => {
  if (apiErr(e).code === "NOT-FOUND") return { activities: [], activity_count: 0 } as AxisCtx;
  throw e;
});

// 「더 보기」로 이어 받은 기록 — 새 상태(S)를 받으면 비운다(옛 applyState 의 meRec 초기화와 같다). 커서는 서버 값 그대로(불투명)
function useMoreRecords(S: AppState) {
  const [m, setM] = useState({ S, extra: [] as Rec[], next: undefined as string | null | undefined, busy: false, err: "" });
  const cur = m.S === S ? m : { S, extra: [], next: undefined, busy: false, err: "" };
  useEffect(() => { if (m.S !== S) setM({ S, extra: [], next: undefined, busy: false, err: "" }); }, [S, m.S]);
  const next = cur.next !== undefined ? cur.next : S.journal_next_before || null;
  async function more() {
    if (!next || cur.busy) return;
    setM({ ...cur, busy: true, err: "" });
    try {
      const j = await meApi.records(next);
      setM(x => (x.S === S ? { ...x, busy: false, extra: x.extra.concat(j.records || []), next: j.next_before || null } : x));
    } catch {
      setM(x => (x.S === S ? { ...x, busy: false, err: MORE_FAIL } : x));
    }
  }
  return { extra: cur.extra, next, busy: cur.busy, err: cur.err, more };
}

export function useWorld(S: AppState) {
  const qc = useQueryClient();
  const stats = useQuery({ queryKey: QK.stats, queryFn: meApi.stats });
  const recs = useMoreRecords(S);
  const axisCtx: Record<string, AxisCtx | null> = {}, personCtx: Record<string, PersonCtx | null> = {};
  for (const [k, q] of qc.getQueriesData<AxisCtx>({ queryKey: ["me", "axis"] })) if (q) axisCtx[String(k[2])] = q;
  for (const [k, q] of qc.getQueriesData<PersonCtx>({ queryKey: ["me", "person"] })) if (q) personCtx[String(k[2])] = q;
  const acts: World["acts"] = {};
  for (const c of [...Object.values(axisCtx), ...Object.values(personCtx)]) for (const a of c?.activities || []) acts[a.id] = a;
  const W: World = { S, recs: (S.journal || []).concat(recs.extra), stats: stats.data || null, axisCtx, personCtx, acts };
  return { W, statsFail: stats.isError, recs };
}
