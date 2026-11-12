// 자료 종류 화면이 상태(S)에서 읽는 것 — 옛 peopleList·reflList·srcName·userTabs·recTabId·qTabId 와 같은 규칙.
import type { AppState } from "../../shared/state";
import { SRC_KIND } from "./text";

export const trashOn = (S: AppState) => !!S.switches?.trash;
export const srcById = (S: AppState, id: string) => (S.sources || []).find(x => x.id === id);
export const srcName = (S: AppState, sid: string) => { const x = srcById(S, sid); return x ? `${x.name}(${SRC_KIND[x.kind] || x.kind})` : "찾을 수 없는 출처"; };
export const meCount = (S: AppState, k: string) => S.me?.counts?.[k] || 0;
export { qTabId, recTabId, userTabs } from "../../shared/tabs";
