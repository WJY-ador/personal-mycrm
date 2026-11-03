// 사용자 정의 탭(질문형·기록형 — blocks[0] = journal 이면 기록형) · 첫 질문형·기록형 탭 주소(없으면 기본 q·journal). 옛 app.html userTabs·qTabId 와 같다.
import { readOk, type AppState, type Tab } from "./state";

export const userTabs = (S: AppState): (Tab & { view: string })[] =>
  (readOk(S, "tabs") ? S.tabs || [] : []).map(t => ({ ...t, view: (t.blocks || [])[0] === "journal" ? "record" : "question" }));
export const recTabId = (S: AppState) => (userTabs(S).find(t => t.view === "record") || { id: "journal" }).id;
export const qTabId = (S: AppState) => (userTabs(S).find(t => t.view === "question") || { id: "q" }).id;
