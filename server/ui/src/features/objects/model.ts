// 자료 종류 화면이 상태(S)에서 읽는 것 — 옛 peopleList·reflList·srcName·userTabs·recTabId·qTabId 와 같은 규칙.
import { readOk, type AppState, type Tab } from "../../shared/state";
import { SRC_KIND } from "./text";

export const trashOn = (S: AppState) => !!S.switches?.trash;
export const srcById = (S: AppState, id: string) => (S.sources || []).find(x => x.id === id);
export const srcName = (S: AppState, sid: string) => { const x = srcById(S, sid); return x ? `${x.name} · ${SRC_KIND[x.kind] || x.kind}` : "찾을 수 없는 출처"; };
export const meCount = (S: AppState, k: string) => S.me?.counts?.[k] || 0;
// 사용자 정의 탭(질문형·기록형) — blocks[0] = journal 이면 기록형
export const userTabs = (S: AppState): (Tab & { view: string })[] =>
  (readOk(S, "tabs") ? S.tabs || [] : []).map(t => ({ ...t, view: (t.blocks || [])[0] === "journal" ? "record" : "question" }));
export const recTabId = (S: AppState) => (userTabs(S).find(t => t.view === "record") || { id: "journal" }).id;
export const qTabId = (S: AppState) => (userTabs(S).find(t => t.view === "question") || { id: "q" }).id;
