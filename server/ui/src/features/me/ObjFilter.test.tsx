// 루틴판 숫자 → 필터 걸린 목록(2026-11-22 구현계획 1절) — 주소 쿼리 → 목록 조회 쿼리 · 걸린 필터 칩 한 줄(최근 N일, 판정, 축, 칸 값) ·
// 칩 누르기 = 그 필터만 풀림 + 주소 쿼리 뗌 · 축 화면의 고정 축은 칩 없음. 문장은 모두 가짜.
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { objFilterOf, objFilterQuery, parseHash } from "../../shared/route";
import { queryClient } from "../../shared/queries";
import { calls, click, installFetch, json, serve, text } from "../../test/fakeServer";
import { installMedia, JOURNAL, layout, meState, STATS } from "../../test/meFixture";
import { hideMe, showMe } from "../../test/showMe";

const OPT = [{ value: "draft", label: "초안" }, { value: "done", label: "완료" }];
const def = (id: string, key: string, label: string, fields: object[] = []) => ({ id, key, label, std_id: null, archived_at: null, fields });
const F = [{ key: "verdict", label: "맞았나", value_type: "text", options: [] }, { key: "stage", label: "단계", value_type: "select", options: OPT }];
const S = () => { const b = meState(); return meState({ definitions: [...b.definitions, def("od_pv", "pivots", "피벗", F), def("od_cp", "collected_posts", "수집 글")] }); };
const page = { object: { id: "od_pv", key: "pivots", label: "피벗" }, columns: [], has_state: false, sort: { key: "title", dir: "asc" },
  filters: [{ key: "stage", label: "단계", values: [{ value: "draft", label: "초안", n: 2 }] }], states: null, total: 1, next_cursor: null,
  rows: [{ id: "v1", code: null, title: "가짜 피벗 하나", revision: 1, updated_at: "2026-11-01T01:00:00+00:00", data: {} }] };

beforeEach(() => {
  installFetch(); installMedia(false); queryClient.clear();
  serve(url => (url === "/api/me/layout" ? json(200, layout()) : url === "/api/me/stats" ? json(200, STATS) : url.startsWith("/api/journal") ? json(200, JOURNAL)
    : url.startsWith("/api/me/objects/") ? json(200, page) : json(200, { activities: [], activity_count: 0 })));
});
afterEach(() => { hideMe(); vi.unstubAllGlobals(); });
const lists = () => calls.filter(c => c.url.startsWith("/api/me/objects/")).map(c => c.url);

test("주소 쿼리 — 화면 판정에서 떼고, 필터로 읽는다(틀린 값 버림) · 거꾸로 만들기", () => {
  expect(parseHash("#_me/obj/pivots?window=7")).toMatchObject({ tab: "_me", a: "obj", b: "pivots", c: "" });
  expect(objFilterOf("window=7&verdict=verdict%3Aunknown&axis=ax1&state=kept&f.stage=draft&x=1"))
    .toEqual({ window: 7, verdict: "verdict:unknown", axis: "ax1", state: "kept", f: { stage: "draft" } });
  expect(objFilterOf("window=0&verdict=verdict:maybe&state=nope")).toEqual({ f: {} });
  expect(objFilterOf("window=91")).toEqual({ f: {} });
  expect(objFilterOf("window=7&state=not_dropped")).toEqual({ window: 7, state: "not_dropped", f: {} });
  expect(objFilterQuery({ window: 7, axis: "ax1" })).toBe("?window=7&axis=ax1");
  expect(objFilterQuery({})).toBe("");
});

test("판정 미확인 링크로 열면 — 목록 조회에 verdict, 머리에 「맞았나: 미확인」 칩 · 누르면 풀리고 주소 쿼리도 뗀다", async () => {
  const el = await showMe("#_me/obj/pivots?verdict=verdict%3Aunknown", S());
  expect(lists()).toEqual(["/api/me/objects/pivots?verdict=verdict%3Aunknown"]);
  expect(text(el, "#obj-filters button")).toEqual(["맞았나: 미확인×"]);
  await click(el.querySelector("#obj-filters button"));
  expect(el.querySelector("#obj-filters")).toBeNull();
  expect(lists().at(-1)).toBe("/api/me/objects/pivots");
  expect(location.hash).toBe("#_me/obj/pivots");
});

test("최근 7일 + 칸 값 — 칩 둘(목록 머리), 하나만 풀면 다른 하나는 남는다 · 버튼 이름 = 칩 글 + 풀기", async () => {
  const el = await showMe("#_me/obj/pivots?window=7&f.stage=draft", S());
  expect(lists()).toEqual(["/api/me/objects/pivots?window=7&f.stage=draft"]);
  expect(text(el, "#obj-filters button")).toEqual(["최근 7일×", "단계: 초안×"]);
  expect(el.querySelector("#obj-filters button")!.getAttribute("aria-label")).toBe("최근 7일, 눌러서 풀기");
  await click(el.querySelector("#obj-filters button"));
  expect(text(el, "#obj-filters button")).toEqual(["단계: 초안×"]);
  expect(lists().at(-1)).toBe("/api/me/objects/pivots?f.stage=draft");
});

test("축 칩 링크 — 최근 7일 + 축(목록 조회 f.axes) · 축 이름은 축 코드", async () => {
  const st = S(), ax = st.definitions.find((d: { key: string }) => d.key === "axes") as { id: string } | undefined;
  const el = await showMe("#_me/obj/collected_posts?window=7&axis=ax1", ax ? { ...st, items: [...st.items, { id: "ax1", object_id: ax.id, code: "A", title: "가짜 축", revision: 1, data: {}, links: [] }] } : st);
  expect(lists()).toEqual(["/api/me/objects/collected_posts?window=7&f.axes=ax1"]);
  expect(text(el, "#obj-filters button")[1]).toMatch(/^축: /);
});

test("들어온 것 링크 — 최근 7일 + 버림 뺌(목록 조회 state=not_dropped), 칩 「버림 뺌」 누르면 풀린다", async () => {
  const el = await showMe("#_me/obj/pivots?window=7&state=not_dropped", S());
  expect(lists()).toEqual(["/api/me/objects/pivots?state=not_dropped&window=7"]);
  expect(text(el, "#obj-filters button")).toEqual(["최근 7일×", "버림 뺌×"]);
  await click(el.querySelectorAll("#obj-filters button")[1]);
  expect(text(el, "#obj-filters button")).toEqual(["최근 7일×"]);
  expect(lists().at(-1)).toBe("/api/me/objects/pivots?window=7");
});

test("목록 막대의 칸 값 칩을 손으로 풀어도 주소 쿼리를 뗀다(새로 고침에 다시 걸리지 않게)", async () => {
  const el = await showMe("#_me/obj/pivots?f.stage=draft", S());
  const bar = [...el.querySelectorAll("button[aria-pressed='true']")].find(b => !b.closest("#obj-filters"))!;
  await click(bar);
  expect(location.hash).toBe("#_me/obj/pivots");
  expect(lists().at(-1)).toBe("/api/me/objects/pivots");
});
