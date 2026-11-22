// 한판 상세(#_me/board/<id>, 명세 4절) — 기호(들어온 것 a, b… 이어서 내가 정한 것) · 소제목마다 「나온 곳」 · 선 = 소제목 × 출처
// · 소제목 마우스 올림/포커스 = 그 출처 카드와 선만 강조 · 카드 누르면 전문(수집 글 AI 요약 = AI 표시 + 문구) · 출처 없음 · 좁은 화면 선 없음 · 404. 문장은 모두 가짜다.
import { act } from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { queryClient } from "../../shared/queries";
import { calls, click, flush, installFetch, json, serve, text } from "../../test/fakeServer";
import { installMedia, JOURNAL, layout, meState, STATS } from "../../test/meFixture";
import { hideMe, showMe } from "../../test/showMe";

const post = (id: string, title: string, o: object = {}) => ({ kind: "post", id, title, author: "가짜 작성자", channel: "reddit", date: "2026-11-20", ai_summary: null, ai: true, ...o });
const rec = (id: string, title: string, o: object = {}) => ({ kind: "record", id, title, date: "2026-11-05", item: null, ...o });
const P1 = post("p1", "가짜 글 하나", { ai_summary: "가짜 AI 요약" }), P2 = post("p2", "가짜 글 둘"),
  R1 = rec("r1", "가짜 기록 하나", { item: { object_key: "pivots", item_id: "v1", title: "가짜 결정", verdict: "미확인" } }), R2 = rec("r2", "가짜 기록 둘", { date: null });
const DETAIL = {
  board: { item_id: "b1", title: "가짜 한판", key_line: "가짜 핵심 한 줄", stage: "draft", date: "2026-11-21" },
  subheads: [{ item_id: "s1", order: 1, text: "가짜 소제목 하나", body: "가짜 전문 하나", sources: [P2, R1] },
    { item_id: "s2", order: 2, text: "가짜 소제목 둘", body: null, sources: [P1, R2, P1] },
    { item_id: "s3", order: 3, text: "출처 없는 소제목", body: "가짜 전문 셋", sources: [] }],
  inflow: [P1, P2], decided: [R1, R2], missing_sources: 0,
};
let DETAIL_REPLY = () => json(200, DETAIL);

beforeEach(() => {
  installFetch(); installMedia(false); queryClient.clear(); DETAIL_REPLY = () => json(200, DETAIL);
  serve(url => (url === "/api/me/layout" ? json(200, layout()) : url === "/api/me/stats" ? json(200, STATS) : url.startsWith("/api/journal") ? json(200, JOURNAL)
    : url.startsWith("/api/me/routine/") ? DETAIL_REPLY() : json(200, { activities: [], activity_count: 0 })));
});
afterEach(() => { hideMe(); vi.unstubAllGlobals(); });
const on = (el: Element, sel: string) => [...el.querySelectorAll(sel)].filter(n => /(^|\s)(_on_\S*|on)(\s|$)/.test(n.getAttribute("class") || "")).map(n => n.getAttribute("data-k") ?? n.getAttribute("data-o") ?? `${n.getAttribute("data-lo")}${n.getAttribute("data-lk")}`);

test("세 단 — 기호 a, b(들어온 것) → c, d(내가 정한 것) · 소제목 1, 2, 3 · 나온 곳 · 출처 없음 · 선 = 소제목 × 출처(중복 제외)", async () => {
  const el = await showMe("#_me/board/b1", meState());
  expect(calls.some(c => c.url === "/api/me/routine/b1")).toBe(true);
  expect(location.hash).toBe("#_me/board/b1");   // 다른 탭으로 넘기지 않는다
  expect(el.querySelector("nav a[aria-current=page]")!.getAttribute("href")).toBe("#_me/summary");
  expect(el.querySelector("#board-detail h2")!.textContent).toBe("가짜 핵심 한 줄");
  expect(el.querySelector("#board-detail .hback a")!.getAttribute("href")).toBe("#_me/summary");
  expect(text(el, "#board-grid h4")).toEqual(["들어온 것", "내가 정한 것", "이렇게 나왔다"]);
  expect([...el.querySelectorAll("#board-grid [data-k]")].map(n => n.getAttribute("data-k"))).toEqual(["a", "b", "c", "d"]);
  expect(text(el, "#board-grid [data-k] button")).toEqual(["a11-20가짜 글 하나", "b11-20가짜 글 둘", "c11-05가짜 기록 하나", "d가짜 기록 둘"]);
  expect(text(el, "#board-grid [data-o] button")).toEqual(["1가짜 소제목 하나", "2가짜 소제목 둘", "3출처 없는 소제목"]);
  expect(text(el, "#board-grid [data-o] > p")).toEqual(["나온 곳: b, c", "나온 곳: a, d", "출처 없음"]);
  expect(el.querySelector("#board-grid [data-o='2']")!.className).toMatch(/nosrc/);
  expect([...el.querySelectorAll("#board-grid svg g")].map(g => `${g.getAttribute("data-lo")}${g.getAttribute("data-lk")}`)).toEqual(["0b", "0c", "1a", "1d"]);
});

test("강조 — 소제목에 마우스 올림이나 포커스 = 그 출처 카드와 선만 on, 격자 흐림 · 떠나면 풀림", async () => {
  const el = await showMe("#_me/board/b1", meState());
  const grid = el.querySelector("#board-grid")!, s1 = grid.querySelector("[data-o='0']")!;
  await act(async () => { s1.dispatchEvent(new MouseEvent("mouseover", { bubbles: true })); });
  expect(grid.className).toMatch(/focus/);
  expect(on(grid, "[data-k]")).toEqual(["b", "c"]);
  expect(on(grid, "[data-o]")).toEqual(["0"]);
  expect(on(grid, "svg g")).toEqual(["0b", "0c"]);
  await act(async () => { s1.dispatchEvent(new MouseEvent("mouseout", { bubbles: true })); });
  expect(grid.className).not.toMatch(/focus/);
  await act(async () => { grid.querySelector<HTMLButtonElement>("[data-o='1'] button")!.focus(); });   // 키보드 = 같은 강조
  expect(on(grid, "[data-k]")).toEqual(["a", "d"]);
  expect(on(grid, "svg g")).toEqual(["1a", "1d"]);
  await act(async () => { grid.querySelector<HTMLButtonElement>("[data-o='1'] button")!.blur(); });
  expect(grid.className).not.toMatch(/focus/);
});

test("카드 누르면 전문 — 수집 글 AI 요약 = AI 표시 + 문구 · 기록 = 이어진 결정과 맞았나 · 소제목 = 본문", async () => {
  const el = await showMe("#_me/board/b1", meState());
  const card = (k: string) => el.querySelector(`#board-grid [data-k='${k}']`)!;
  await click(card("a").querySelector("button"));
  expect(card("a").querySelector("button")!.getAttribute("aria-expanded")).toBe("true");
  expect(card("a").querySelector(".chip.o-ai")!.textContent).toBe("AI 요약");
  expect(card("a").textContent).toContain("AI가 만든 요약이에요");
  expect(card("a").textContent).toContain("가짜 작성자, reddit, 11월 20일");
  await click(card("b").querySelector("button"));
  expect(card("b").querySelector(".chip.o-ai")).toBeNull();   // 요약이 없으면 AI 표시도 없음
  await click(card("c").querySelector("button"));
  expect(card("c").textContent).toContain("가짜 결정. 맞았나: 미확인");
  const s1 = el.querySelector("#board-grid [data-o='0']")!;
  await click(s1.querySelector("button"));
  expect(s1.textContent).toContain("가짜 전문 하나");
  await click(s1.querySelector("button"));
  expect(s1.textContent).not.toContain("가짜 전문 하나");
});

test("좁은 화면 — 선(svg) 없이 세 단 위아래, 나온 곳 글자는 그대로", async () => {
  installMedia(true);
  const el = await showMe("#_me/board/b1", meState());
  expect(el.querySelector("#board-grid svg")).toBeNull();
  expect(text(el, "#board-grid [data-o] > p")).toEqual(["나온 곳: b, c", "나온 곳: a, d", "출처 없음"]);
});

test("없는 항목·남의 항목(404) = 열 수 없음 한 줄 + 루틴판으로", async () => {
  DETAIL_REPLY = () => json(404, { code: "NOT-FOUND", msg: "" });
  const el = await showMe("#_me/board/zz", meState());
  await flush();
  expect(el.querySelector("#board-detail .empty")!.textContent).toBe("이 데이터를 열 수 없어요.");
  expect(el.querySelector("#board-grid")).toBeNull();
});
