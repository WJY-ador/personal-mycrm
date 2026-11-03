// Setup 「페이지 레이아웃」 저장 줄(옛 app.html LAY·layCommit·laySend 그대로) — 놓을 때 PUT 1 · 한 번에 하나(보내는 중이면 마지막 배치만
// 줄 세워 응답 뒤 보낸다 — 옛 응답이 새 배치를 덮지 않는다) · 실패 = 마지막 저장 배치로 복원 + 한 줄 · LAYOUT-STALE = 서버 배치를 다시 받아 그대로.
// 마지막 저장 배치 = 「나」와 같은 조회 캐시(QK.layout) — 저장 응답을 캐시에 넣으면 「나」도 그 배치로 그린다(옛 crm:state 대신).
import { useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiErr } from "../../../shared/api";
import { queryClient } from "../../../shared/queries";
import { meApi, type Layout, type MePage } from "../meApi";
import { validTabs } from "../text";
import { QK } from "../useWorld";

type Op = { kind: "put"; page: MePage } | { kind: "reset" };
export const LAY_TEXT = {
  saving: "저장하고 있어요…",
  saved: "저장했어요.",
  reset: "기본 배치로 되돌렸어요.",
  stale: "다른 화면에서 먼저 바뀌어 최신 배치를 불러왔어요. 다시 옮겨 주세요.",
  offline: "서버에 연결하지 못해 저장하지 않았어요. 잠시 뒤 다시 옮겨 주세요.",
  fail: "저장하지 못해 전 배치로 돌렸어요. 다시 옮겨 주세요.",
  noApi: "레이아웃을 불러오지 못해 기본 배치를 보여 드려요. 새로 고침해 주세요.",
};

const cached = () => queryClient.getQueryData<Layout>(QK.layout);
const pageOf = (l: Layout | undefined) => { const p = l?.layout?.pages?.me; return p && validTabs(p.tabs) ? p : null; };

export function useLay(def: MePage) {
  const q = useQuery({ queryKey: QK.layout, queryFn: meApi.layout });
  const [cur, setCur] = useState<MePage | null>(null);   // 보내는 중인 배치(화면은 바로 새 배치) — 없으면 마지막 저장 배치
  const [msg, setMsg] = useState({ text: "", err: false });
  const line = useRef({ busy: false, queued: null as Op | null });

  async function send(op: Op) {
    const L = line.current;
    L.busy = true;
    try {
      const res = op.kind === "reset" ? await meApi.layoutReset() : await meApi.layoutPut(op.page, cached()?.version || 0);
      queryClient.setQueryData(QK.layout, res);   // 복원 뒤 다음 PUT 은 이 version(서버가 +1)
      if (!L.queued) setCur(null);
      setMsg({ text: op.kind === "reset" ? LAY_TEXT.reset : LAY_TEXT.saved, err: false });
    } catch (e) {
      const err = apiErr(e);
      L.queued = null;
      if (err.code === "LAYOUT-STALE") {   // 다른 탭·화면이 먼저 바꿈 — 서버 배치를 받아 그대로 보여 준다(못 받으면 마지막 저장 배치)
        const g = await meApi.layout().catch(() => null);
        if (g && pageOf(g)) queryClient.setQueryData(QK.layout, g);
        setMsg({ text: LAY_TEXT.stale, err: true });
      } else setMsg({ text: err.code === "OFFLINE" ? LAY_TEXT.offline : LAY_TEXT.fail, err: true });
      setCur(null);
    }
    L.busy = false;
    const next = L.queued;
    if (next) { L.queued = null; setMsg({ text: LAY_TEXT.saving, err: false }); void send(next); }
  }

  function commit(op: Op) {
    if (op.kind === "put") setCur(op.page);
    setMsg({ text: LAY_TEXT.saving, err: false });
    if (line.current.busy) line.current.queued = op; else void send(op);
  }

  const page = cur || pageOf(q.data) || def;
  // 순서 바꾸기 — grp(tabs|summary)의 key 를 to 자리로. 바뀐 게 있으면 PUT 1(요약 블록은 칸째 옮긴다 — props 그대로)
  function move(grp: "tabs" | "summary", key: string, to: number): boolean {
    const tabs = page.tabs.slice(), slots = (page.regions.summary || def.regions.summary).slice();
    const list: unknown[] = grp === "tabs" ? tabs : slots;
    const from = grp === "tabs" ? tabs.indexOf(key) : slots.findIndex(s => s.c === key);
    to = Math.max(0, Math.min(list.length - 1, to));
    if (from < 0 || from === to) return false;
    list.splice(to, 0, list.splice(from, 1)[0]);
    commit({ kind: "put", page: { ...page, tabs, regions: { ...page.regions, summary: slots } } });
    return true;
  }
  return { pending: q.isPending, api: q.isSuccess, page, msg, move, reset: () => commit({ kind: "reset" }) };
}
