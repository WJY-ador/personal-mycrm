// 주소 판정(옛 app.html route·pickTab·navReplace·renderSetup·setupPages — 옛 test_web_home.py test_static·test_trash_switch 를 실행 시험으로)
import { expect, test } from "vitest";
import { resolve, setupPages, type View } from "./route";
import type { AppState } from "./state";

const S = {
  user: { display_name: "홍길동", nav: "new" }, switches: { trash: false },
  tabs: [{ id: "t-001", label: "일지", blocks: ["journal"] }, { id: "t-002", label: "질문", blocks: ["sheet"] }],
  definitions: [{ id: "d1", std_id: "std:principles", fields: [] }, { id: "d2", std_id: null, fields: [] }],
  items: [{ id: "p1", object_id: "d1", revision: 2 }, { id: "x1", object_id: "d2", revision: 1 }], item_proposals: [{ id: "n1", object_id: "d1", revision: 0 }],
} as unknown as AppState;
const go = (h: string, st: AppState = S, last = {}) => resolve(h, st, last) as Exclude<View, { replace: string }>;
const rep = (h: string, st: AppState = S) => (resolve(h, st) as { replace?: string }).replace;

test("옛 묶음 주소 = 새 자리로 replace", () => {
  expect(["#_obj", "#_settings", "#_settings/structure", "#_devices", "#map", "#_inbox", "#_inbox/i1", "#today", "#home/x", "#structure/defs",
    "#structure/d1/p1", "#structure/d2/x1", "#_setup/nope", "#_setup/trash"].map(h => rep(h)))
    .toEqual(["#_setup/objects", "#_setup/structure", "#_setup/structure", "#_setup/pc", "#_setup/map", "#_today", "#_today/inbox/i1", "#_today",
      "#_today", "#_setup/structure", "#_me/principle/p1", "#_me/custom/x1", "#_setup/layout", "#_setup/layout"]);
  expect([rep("#structure/d1/n1"), rep("#structure/d1"), rep("#map/review/q1/c1"), rep("#today/review/q1/c1"), rep("#_inbox/applied")]).toEqual([undefined, undefined, undefined, undefined, undefined]);
});

test("화면 고르기 — 탭 줄 · 사용자 탭 · 옛 화면 · 모르면 「나」 · Setup 페이지", () => {
  const pick = (h: string) => { const v = go(h); return [v.screen, v.args, v.cur, v.setup, v.navnew]; };
  expect(pick("")).toEqual(["me", ["", ""], "_me", null, true]);
  expect(pick("#nope")).toEqual(["me", ["", ""], "_me", null, true]);
  expect(pick("#_me/principle/p1")).toEqual(["me", ["principle", "p1"], "_me", null, true]);
  expect(pick("#_today/inbox/i1")).toEqual(["today", ["today", "inbox", "i1"], "_today", null, true]);
  expect(pick("#_inbox/applied")).toEqual(["today", ["inbox", "applied"], "_today", null, true]);
  expect(pick("#t-001/r9")).toEqual(["sheet", ["t-001", "record", "journal", "r9"], "_setup", "objects", false]);
  expect(pick("#t-002")).toEqual(["sheet", ["t-002", "question", "sheet", ""], "_setup", null, false]);
  expect(pick("#q/q1")).toEqual(["sheet", ["q", "question", "sheet candidates next", "q1"], "_setup", null, false]);
  expect(pick("#journal")).toEqual(["sheet", ["journal", "record", "journal next candidates", ""], "_setup", "objects", false]);
  expect(pick("#structure/d1")).toEqual(["structure", ["d1", ""], "_setup", "objects", false]);
  expect(pick("#_obj/person/p9")).toEqual(["objects", ["person", "p9", ""], "_setup", "objects", true]);
  expect(pick("#_obj/activity/a1")).toEqual(["activity", ["activity", "a1", ""], "_setup", "objects", true]);
  expect(pick("#_setup")).toEqual(["layout", [], "_setup", "layout", true]);
  expect(pick("#_setup/objects/axis/x1")).toEqual(["activity", ["axis", "x1", ""], "_setup", "objects", true]);
  expect(pick("#_setup/objects/source/s1")).toEqual(["objects", ["source", "s1", ""], "_setup", "objects", true]);
  expect(pick("#_setup/structure")).toEqual(["defs", [], "_setup", "structure", true]);
  expect(pick("#_setup/map")).toEqual(["map", ["map"], "_setup", "map", true]);
  expect(pick("#_setup/migration/pl1")).toEqual(["migration", ["pl1"], "_setup", "migration", true]);
  expect(pick("#_setup/help")).toEqual(["help", [], "_setup", "help", true]);
  expect(go("#t-001", { ...S, read: { tabs: { ok: false } } } as AppState).screen).toBe("me");   // 탭 설정 못 읽음 = 사용자 탭 없음
});

test("판단 검토 — 돌아갈 곳: 질문형 = 그 질문 한 장, 그 외 = 그 탭에서 마지막으로 본 주소 · Setup 줄 없음 · 기억하지 않음", () => {
  expect(go("#q/review/q1/c1").args).toEqual(["q", "q1", "c1", "#q/q1", "질문으로 돌아가기"]);
  expect(go("#q/review/r:r1/c1").args).toEqual(["q", "r:r1", "c1", "#q", "질문으로 돌아가기"]);
  const v = go("#journal/review/r:r1/c1", S, { journal: "#journal/r1" });
  expect([v.screen, v.args, v.setup, v.remember, v.navnew]).toEqual(["review", ["journal", "r:r1", "c1", "#journal/r1", "기록으로 돌아가기"], null, false, false]);
  expect(go("#map/review/q1/c1").args.slice(3)).toEqual(["#map", "지도로 돌아가기"]);
  expect(go("#structure/review/r:r1/c1").args.slice(3)).toEqual(["#structure", "구조로 돌아가기"]);
  expect(go("#t-001/review/r:r1/c1").args.slice(3)).toEqual(["#t-001", "일지로 돌아가기"]);
});

test("휴지통 스위치 — 꺼짐·필드 없음 = 페이지 0 · 켜짐 = Setup 맨 끝 「휴지통」", () => {
  const pages = (sw: object) => setupPages({ ...S, switches: sw } as AppState).map(p => p[0]);
  expect(pages({ converse: true })).not.toContain("trash");
  expect(pages({ trash: false })).not.toContain("trash");
  expect(pages({ trash: true })).toEqual(["layout", "structure", "objects", "pc", "map", "help", "migration", "trash"]);
  expect(go("#_setup/trash", { ...S, switches: { trash: true } } as AppState).screen).toBe("trash");
});

test("옛 「연결 장치」 주소는 「이 PC」로 — 연결 장치 페이지는 설정 줄에 없다", () => {
  expect(go("#_setup/devices")).toEqual({ replace: "#_setup/pc" });
  expect(setupPages(S).map(p => p[0])).not.toContain("devices");
  expect(go("#_setup/pc").screen).toBe("pc");
});
