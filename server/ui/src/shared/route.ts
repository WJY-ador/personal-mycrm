// 주소(hash) → 화면 판정 한 벌(옛 app.html route·pickTab·navOn·navReplace·renderSetup·objMount). 껍데기 라우터(layout/App)와
// 문의를 보낸 자리(features/desk deskPage)가 같이 쓴다 — 판정을 두 곳에 두지 않는다. 순수 함수(상태 S + 주소만 읽는다).
import type { AppState, Item } from "./state";
import { roJosa } from "./LoadFail";
import { userTabs } from "./tabs";

export type Route = { tab: string; a: string; b: string; c: string; d: string };
export type TabDef = { id: string; label: string; view: string; blocks: string[] };

export function parseHash(hash: string): Route {
  let s = hash.replace(/^#/, "");
  try { s = decodeURIComponent(s); } catch { /* 깨진 % 꼴 — 글자 그대로 */ }
  const p = s.split("/");
  return { tab: p[0] || "", a: p[1] || "", b: p[2] || "", c: p[3] || "", d: p[4] || "" };
}

// 코어 화면 라벨 — 한 줄씩 바꾸면 옛 화면 탭 이름·판단 검토 「…으로 돌아가기」가 같이 바뀐다
export const LABELS = { question: "질문", record: "기록", structure: "구조", map: "지도" };
// 탭 줄에 없는 옛 화면(질문·기록·구조·지도) — 「자료 종류」·Setup·「나」의 링크(#q·#journal·#structure…)로 열린다.
// blocks 는 옛 기본 탭과 같은 해석 — 질문형은 sheet·candidates·next, 기록형은 journal·next·candidates.
const BASE: Record<string, TabDef> = {
  q: { id: "q", label: LABELS.question, view: "question", blocks: ["sheet", "candidates", "next"] },
  journal: { id: "journal", label: LABELS.record, view: "record", blocks: ["journal", "next", "candidates"] },
  structure: { id: "structure", label: LABELS.structure, view: "structure", blocks: [] },
  map: { id: "map", label: LABELS.map, view: "map", blocks: [] },
};
// 새 화면 id 는 「_」 로 시작한다 — 사용자 탭 id(t-001 꼴)·기본 탭 id(today·q·journal·structure·map·home)와 겹치지 않는다
const NAVTAB: Record<string, TabDef> = {
  _me: { id: "_me", label: "나", view: "me", blocks: [] },
  _obj: { id: "_obj", label: "자료 종류", view: "objects", blocks: [] },
  _settings: { id: "_settings", label: "내 구조 설정", view: "settings", blocks: [] },
  _devices: { id: "_devices", label: "이 PC", view: "devices", blocks: [] },   // 옛 주소(#_devices) — 「이 PC」로 돌린다
  _inbox: { id: "_inbox", label: "저장 승인 대기", view: "inbox", blocks: [] },
  _today: { id: "_today", label: "오늘", view: "today2", blocks: [] },
  _setup: { id: "_setup", label: "설정", view: "setup", blocks: [] },
};
// 탭 줄 = 「나」 · 「오늘」(+ 톱니 Setup). 질문·기록·사용자 정의 탭은 「자료 종류」에서 들어간다(#<탭 id> 링크로 열리고 탭 줄은 Setup 을 켠다)
export const NAV_TABS = [NAVTAB._me, NAVTAB._today];

// 탭 줄 탭 → 사용자 정의 탭 ID → 옛 화면(BASE) → 탭 줄에 없는 새 화면(NAVTAB). 모르면 첫 탭
export function pickTab(R: Route, S: AppState): TabDef {
  const id = R.tab;
  return NAV_TABS.find(t => t.id === id) || userTabs(S).find(t => t.id === id) || BASE[id] || NAVTAB[id] || NAV_TABS[0];
}
// 탭 줄에 없는 화면이 켤 탭 — 승인 대기 = 「오늘」, 자료 종류·지도·내 구조 설정·연결 장치·항목 보기·질문·기록·사용자 탭 = Setup
const navOn = (t: TabDef) => ({ _inbox: "_today", structure: "_setup", _obj: "_setup", _settings: "_setup", _devices: "_setup", map: "_setup" } as Record<string, string>)[t.id] ||
  (t.view === "question" || t.view === "record" ? "_setup" : t.id);

// 「나」 의 탭(기본 종류 = 표준 정의 std_id) — 항목 하나를 어느 탭에서 여는지. features/me 도 이것을 쓴다
export const ME_STD: Record<string, string> = { principle: "std:principles", decision: "std:decision_events", axis: "std:axes" };
export function meTabOf(S: AppState, it: Item): "principle" | "decision" | "axis" | "custom" {
  const d = (S.definitions || []).find(x => x.id === it.object_id);
  for (const t of ["principle", "decision", "axis"] as const) if (d && d.std_id === ME_STD[t]) return t;
  return "custom";
}

// 옛 묶음 주소 → 새 주소(replace). 없으면 ""
function navReplace(R: Route, S: AppState): string {
  if (R.tab === "_obj" && !R.a) return "#_setup/objects";
  if (R.tab === "_settings") return "#_setup/structure";
  if (R.tab === "_devices") return "#_setup/pc";
  if (R.tab === "map" && R.a !== "review") return "#_setup/map";   // 지도의 [대조](#map/review/…)는 판단 검토로
  if (R.tab === "_inbox" && !R.a) return "#_today";
  if (R.tab === "_inbox" && !["pending", "applied", "excluded", "expired", "all"].includes(R.a)) return "#_today/inbox/" + encodeURIComponent(R.a);   // 대기 글 하나 — 같은 상세를 오늘 안에서
  if ((R.tab === "today" || R.tab === "home") && R.a !== "review") return "#_today";   // 옛 오늘 화면은 없다 — 옛 대조 링크(#today/review/…)만 그대로
  // 항목 보기 — 적용된 항목 하나만 「나」 의 그 탭으로. 정의별 카드 그리드(#structure·#structure/<정의>)는 새 항목 제안(서랍)이 「나」 에 없어 그대로
  if (R.tab === "structure") {
    if (R.a === "defs") return "#_setup/structure";
    const d = (S.definitions || []).find(x => x.id === R.a);
    const it = d && R.b ? (S.items || []).concat(S.item_proposals || []).find(x => x.id === R.b) : undefined;
    if (it && it.revision) return `#_me/${meTabOf(S, it)}/${encodeURIComponent(R.b)}`;
  }
  return "";
}

// Setup 페이지 줄 — 휴지통은 스위치 켜짐일 때만. 꺼짐이면 #_setup/trash 는 레이아웃으로 돌린다
// 「연결 장치」는 사용자 화면에서 없앴다(2026-11-13 앱 하나 자동 연결) — 「이 PC」 한 줄. 옛 주소 #_setup/devices 는 이 PC 로
const SETUP_PAGES: [string, string][] = [["layout", "페이지 레이아웃"], ["structure", "내 구조 설정"], ["objects", "자료 종류"], ["pc", "이 PC"],
  ["map", "지도"], ["help", "문의 및 개인정보"], ["migration", "이관"]];
export const setupPages = (S: AppState) => (S.switches?.trash ? SETUP_PAGES.concat([["trash", "휴지통"]]) : SETUP_PAGES);
const SETUP_SCREEN: Record<string, string> = { layout: "layout", structure: "defs", pc: "pc", map: "map", trash: "trash", migration: "migration", help: "help" };

// 자료 종류 — 활동·축 상세는 「활동」 화면, 그 밖(색인·사람·출처·읽고 든 생각)은 「자료 종류」 화면
const objScreen = (a: string, b: string, c: string): [string, string[]] => (a === "activity" || a === "axis" ? ["activity", [a, b, c]] : ["objects", [a, b, c]]);

// 판정 결과 — replace(옛 주소 → 새 주소) 또는 #view 화면 하나 + 탭 줄·Setup 줄·머리글 상태
export type View = { replace: string } | {
  replace?: undefined;
  tab: TabDef; cur: string;            // cur = 탭 줄에서 켤 탭 id
  screen: string; args: string[];      // 화면 이름(layout/registry SCREENS 키) · 주소 조각
  setup: string | null;                // Setup 페이지 줄에서 켤 페이지(null = 줄 없음)
  navnew: boolean;                     // 새 화면 = 머리글 날짜·스펙트럼 숨김(body.navnew-screen)
  remember: boolean;                   // 판단 검토에서 돌아갈 곳으로 이 주소를 기억한다
};

// lastView = 탭마다 마지막으로 본 주소(판단 검토의 「돌아가기」) — 껍데기가 기억한다
export function resolve(hash: string, S: AppState, lastView: Record<string, string> = {}): View {
  const R = parseHash(hash);
  const to = navReplace(R, S);
  if (to) return { replace: to };
  const tab = pickTab(R, S), cur = navOn(tab);
  const navnew = R.a !== "review" && ["me", "objects", "settings", "devices", "inbox", "map", "today2", "setup"].includes(tab.view);
  const v = (screen: string, args: string[], setup: string | null = null) => ({ tab, cur, screen, args, setup, navnew, remember: true });
  const inSetup = cur === "_setup" && tab.view !== "question" ? "objects" : null;   // Setup 안 화면(자료 종류의 상세·옛 항목 보기 포함) = Setup 줄
  if (R.a === "review") {   // 판단 검토 — 질문형 탭은 그 질문 한 장, 그 외 = 그 탭에서 마지막으로 본 화면
    const qk = tab.view === "question" && !R.b.startsWith("r:");
    return { ...v("review", [tab.id, R.b, R.c, qk ? `#${tab.id}/${R.b}` : (lastView[tab.id] || `#${tab.id}`), qk ? "질문으로 돌아가기" : `${tab.label}${roJosa(tab.label)} 돌아가기`]),
      setup: null, remember: false };
  }
  const sheet = (view: string) => v("sheet", [tab.id, view, (tab.blocks || []).join(" "), R.a], inSetup);
  switch (tab.view) {
    case "structure": return v("structure", [R.a, R.b], inSetup);
    case "map": return v("map", [tab.id], inSetup);
    case "record": return sheet("record");
    case "me": return v("me", [R.a, R.b]);
    case "today2": return v("today", ["today", R.a, R.b]);
    case "objects": { const [s, a] = objScreen(R.a, R.b, R.c); return v(s, a, inSetup); }
    case "settings": return v("defs", [], inSetup);
    case "devices": return { replace: "#_setup/pc" };
    case "inbox": return v("today", ["inbox", R.a]);   // 지난 승인 대기(오늘과 같은 화면 묶음)
    case "setup": {
      if (R.a === "devices") return { replace: "#_setup/pc" };   // 옛 「연결 장치」 주소
      const page = setupPages(S).some(p => p[0] === R.a) ? R.a : "layout";
      if (R.a && page !== R.a) return { replace: "#_setup/" + page };
      if (page === "objects") { const [s, a] = objScreen(R.b, R.c, R.d); return v(s, a, page); }
      return v(SETUP_SCREEN[page], page === "map" ? [BASE.map.id] : page === "migration" ? [R.b] : [], page);
    }
    default: return sheet("question");
  }
}

// 표시 이름이 비면 이름 관문(다른 화면 대신)
export const needName = (S: AppState) => !!(S.user && "display_name" in S.user && !S.user.display_name);
