// 「나」 보기 상태(쓰기 아님) — 연결 보기 방식(그래프/목록: 이 화면에 머무는 동안) · 종류 거르기·「더 N」 펼침(같은 가운데 데이터인 동안).
// 1열(좁은 폭) 여부 = shared/mobile.ts.
import { createContext, useContext, useState } from "react";
export { useMobile } from "../../shared/mobile";

export function useViewStore(center: string) {
  const [mode, setMode] = useState<"graph" | "list">("graph");
  const [f, setF] = useState({ center, kind: "", open: [] as string[] });
  const cur = f.center === center ? f : { center, kind: "", open: [] };
  return {
    mode, kind: cur.kind, isOpen: (k: string) => cur.open.includes(k),
    toggle: () => setMode(m => (m === "graph" ? "list" : "graph")),
    setKind: (kind: string) => setF({ ...cur, kind }),
    open: (k: string) => setF({ ...cur, open: [...cur.open, k] }),
  };
}
export type ViewStore = ReturnType<typeof useViewStore>;
export const ViewCtx = createContext<ViewStore | null>(null);
export const useView = () => useContext(ViewCtx)!;

// 1열 목록 → 상세로 갈 때 — 돌아올 자리(페이지 위치)와 「목록에서 왔다」(뒤로 = history.back). 이 화면에 머무는 동안만
export const backNav = { fromList: false, y: 0 };
