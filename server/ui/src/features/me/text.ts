// 「나」 화면 문구·고정 값(옛 app.html 「나」 상세·v9 절 글자 그대로). 여러 화면이 같이 쓰는 낱말은 shared(words·source·item)에서 다시 내보낸다.
import type { ApiError } from "../../shared/api";

// 고정 탭 6 + 오브젝트 탭(obj:<key>, 사용자 오브젝트마다 하나 — 2026-11-18 오브젝트 탭). 오브젝트 탭 이름 = 그 오브젝트 label
export const ME_TABS = ["summary", "principle", "decision", "axis", "person", "source"] as const;
export type MeTab = (typeof ME_TABS)[number];
export const isTab = (t: string | undefined): t is MeTab => (ME_TABS as readonly string[]).includes(t || "");
export const OBJ_TAB = "obj:";
export const objTabKey = (t: string) => (t.startsWith(OBJ_TAB) ? t.slice(OBJ_TAB.length) : "");
// 저장값이 고정 6탭을 한 번씩 + 오브젝트 탭이 아니면(빠짐·중복·모르는 이름) 기본 배치(「나」·Setup 페이지 레이아웃 공용)
export const validTabs = (t: unknown): t is string[] => Array.isArray(t) && new Set(t).size === t.length && ME_TABS.every(x => t.includes(x))
  && t.every(x => typeof x === "string" && (isTab(x) || /^obj:[a-z][a-z0-9_]{0,39}$/.test(x)));
// 탭 순서를 지금 오브젝트에 맞춘다 — 서버 db.me_tabs_fit 과 같은 규칙(서버가 정본, 화면은 레이아웃을 다시 받기 전 새로 적용·보관한 오브젝트만 맞춘다).
// 옛 custom 자리 = 오브젝트 탭들 · 없는 오브젝트 탭은 뺀다 · 빠진 탭은 사람·출처 가운데 앞선 것 바로 앞(둘 다 없으면 끝)
export function fitTabs(tabs: string[], keys: string[]): string[] {
  const want = keys.map(k => OBJ_TAB + k), out: string[] = [];
  for (const t of tabs) {
    if (t === "custom") out.push(...want.filter(w => !tabs.includes(w) && !out.includes(w)));
    else if (t.startsWith(OBJ_TAB)) { if (want.includes(t) && !out.includes(t)) out.push(t); }
    else out.push(t);
  }
  const miss = want.filter(w => !out.includes(w));
  const at = Math.min(...["person", "source"].map(t => out.indexOf(t)).filter(i => i >= 0), out.length);
  out.splice(at, 0, ...miss);
  return out;
}
export const ME_TAB_LABEL: Record<MeTab, string> = { summary: "요약", principle: "기준", decision: "결정", axis: "축", person: "사람", source: "출처" };
// 탭 이름 — 고정 탭 = 위 표, 오브젝트 탭 = 그 오브젝트 label(정의를 못 찾으면 key)
export const tabLabel = (defs: { key: string; label: string }[] | undefined, t: string) =>
  isTab(t) ? ME_TAB_LABEL[t] : (defs || []).find(d => d.key === objTabKey(t))?.label || objTabKey(t) || t;
export { isAnyMeStd, isMeStd } from "../../shared/route";
export const ME_LOCKED = new Set(["principle", "decision", "axis", "person", "source"]);
export const ME_LENS: Partial<Record<MeTab, string>> = { principle: "근거 역추적", decision: "근거 역추적", axis: "축 묶음", person: "사람 관계" };
export const URL_KINDS = ["journal", "q", "cand", "item", "refl"];
// 오브젝트 탭 목록 보기 문구 — 판별 상태(수집 글, collected_states)는 오늘 탭 수집 인박스와 같은 낱말
export const OBJ_STATE: [string, string][] = [["pending", "대기"], ["kept", "보관"], ["dropped", "버림"]];
export const OBJ_TEXT = {
  search: "제목 검색", state: "상태", title: "제목", link: "원문", more: "더 보기", none: "조건에 맞는 항목이 없어요.",
  fail: "목록을 불러오지 못했어요.", retry: "다시 불러오기", back: "목록으로", gone: "이 오브젝트 탭은 없어요. 보관했거나 이름이 바뀌었을 수 있어요.",
  window: (n: number) => `최근 ${n}일`, axis: "축", on: "걸린 필터", off: "눌러서 풀기", notDropped: "버림 뺌",   // 목록 머리 걸린 필터 칩(2026-11-22)
  routed: (n: number, m: number) => `자동 분류 ${n}건, 분류 못 함 ${m}건`,   // 담을 규칙이 있는 오브젝트만(2026-11-18 구조추천)
  board: "한판으로 보기",   // 루틴판 한판 오브젝트 항목 페이지 링크(2026-11-21)
};
// 축 탭(축 잇기, 2026-11-18 명세 4.1) — 축 카드 목록 · 축 화면([한 장], 수집 글, 원하는 관점과 키워드)
export const AXIS_TEXT = {
  list: "축", empty: "축이 아직 없어요. 축 항목이 생기면 여기에 보여요.", pending: "대기", kept: "보관", hasPage: "한 장 있음",
  back: "축 목록", page: "한 장", aiMark: "AI가 쓴 초안이에요. 판단 근거가 아니에요.", noPage: "아직 한 장이 없어요.",
  updated: (t: string) => `${t} 갱신`, fold: "원하는 관점과 키워드", keywords: "키워드", noBody: "원하는 관점이 아직 없어요.",
  // 한 장 그 자리 편집·내 판·사례(2026-11-22)
  mineMark: "내가 고친 판 · ", aiNewer: (t: string) => `새 AI 초안이 왔어요${t ? `(${t})` : ""}`, aiNone: "AI 초안 본문을 불러오지 못했어요.",
  editTip: "두 번 누르거나 Enter 로 고치기", editHint: "저장 Cmd+Enter · 취소 Esc", saving: "저장하고 있어요…", editLabel: "한 장 마크다운",
  stale: "다른 곳에서 먼저 바뀌었어요. 쓰던 글은 상자에 그대로 있어요. 복사해 두고 새로 고침해 주세요.", caseMark: "사례",
};
// 자동 분류 항목 페이지(2026-11-18 구조추천 명세 6.5) — 표시, 근거 원문, 빼기
export const ROUTE_TEXT = {
  mark: "자동 분류", src: "근거 원문", gone: "원문이 휴지통에 있어요.", loading: "원문을 불러오는 중이에요…", fail: "원문을 불러오지 못했어요.",
  exclude: "빼기", ask: "이 항목을 자동 분류에서 뺄까요? 같은 원문은 다시 들어오지 않아요. 원문 기록은 그대로예요.",
  done: "뺐어요. 원문 기록은 그대로예요.",
};

export { ME_EMPTY } from "../../shared/words";
export const STATS_FAIL = "통계를 불러오지 못했어요. 새로 고침해 주세요.";
export const GONE = "이 데이터를 열 수 없어요.";
export { LOADING } from "../../shared/words";
export const NO_CONN = "연결된 데이터가 없어요.";
export const CONN_FAIL = "연결을 불러오지 못했어요.";
export const MORE_FAIL = "더 불러오지 못했어요. 다시 눌러 주세요.";
export { SRC_KIND, SRC_NONE } from "../../shared/source";
export { REFL_KIND } from "../../shared/words";
export { TRASH_ASK, TRASH_DONE } from "../../shared/item";
export const OFFLINE = "서버에 연결하지 못했어요. 잠시 뒤 다시 해 주세요.";

export const firstLine = (s: string | null | undefined) => (String(s || "").split("\n").find(l => l.trim()) || "").trim();

// 기존 쓰기(표시 이름·읽고 든 생각·판단·항목 결정) 실패 — 원인 + 다음 행동 2문장(옛 homeErrText 그대로)
export function oldErrText(e: ApiError): string {
  if (e.code === "CONFLICT") return "다른 곳에서 먼저 바뀌었어요. 최신 내용을 다시 불러왔으니 확인하고 다시 해 주세요.";
  if (e.code === "OFFLINE") return OFFLINE;
  if (e.code === "CANDIDATE-REVIEW") return `${e.msg || "근거 글이 인용 조건에 맞지 않아 남길 수 없어요."} 반영 안 함으로는 표시할 수 있어요.`;
  const m = String(e.msg || "저장하지 못했어요.").trim();
  return `${/[.?!요]$/.test(m) ? m : m + "."} 고친 뒤 다시 해 주세요.`;
}

// 수기 수정(기록 본문·제목·항목) 실패 — 서버 문구(msg)와 다음 행동(action)을 그대로. 화면이 문구를 짓지 않는다(연결 실패만 화면 문구)
export const serverErrText = (e: ApiError) => (e.code === "OFFLINE" ? OFFLINE : [e.msg, e.action].filter(Boolean).join(" ") || "저장하지 못했어요.");
