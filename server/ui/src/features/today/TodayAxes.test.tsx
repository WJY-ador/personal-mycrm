// 「오늘」 머리 「오늘의 축」(축 잇기, 2026-11-18 명세 4.2) — 축별 대기 수 막대 + 축 목록(코드, 이름, 수) · 누르면 축 화면 ·
// 대기 0 축 숨김(색 번호는 전체 순서 그대로) · 축 없음, 대기 합 0 = 막대 없음 · 못 불러옴 = 한 줄 · 수집 인박스 카드 축 코드 칩 · 판별 뒤 대기 수 다시 받기.
import { afterEach, beforeEach, expect, test } from "vitest";
import { queryClient } from "../../shared/queries";
import { calls, click, installFetch, json, serve, text } from "../../test/fakeServer";
import { installMedia } from "../../test/meFixture";
import { byText, hideScreen, showScreen } from "../../test/showScreen";

type P = Record<string, unknown>;
const ax = (id: string, code: string, title: string, pending: number) => ({ id, code, title, description: "", keywords: [], counts: { pending, kept: 0, total: pending }, page: null });   // 서버 꼴
let AXES: P[] = [], OV_OK = true, PEND: P[] = [];
const post = (id: string, axes: P[]): P => ({ id, revision: 1, title: `${id} 제목`, channel: null, author_display: `${id} 작성자`, post_url: null, posted_on: null,
  collected_on: "2026-11-12", axes, ai: { grade: "signal", summary: null, as_is: null, to_be: null, ops: null, points: null }, state: "pending", decided_by: null, decided_at: null });
const S = { user: { nav: "new" }, switches: {}, activity_ui: { actions: {}, providers: {}, pending_days: 30 }, inbox: { pending: 0 }, journal: [] };
const show = () => showScreen("today", "#_today", ["today", "", ""], S);
const ovCalls = () => calls.filter(c => c.url === "/api/axes").length;

beforeEach(() => {
  installFetch(); installMedia(false); queryClient.clear(); OV_OK = true;
  AXES = [ax("a1", "A", "합성 축 하나", 3), ax("a2", "B-1", "합성 축 둘", 0), ax("a3", "C", "합성 축 셋", 2)];
  PEND = [post("p1", [{ id: "a1", title: "합성 축 하나" }, { id: "a9", title: "모르는 축" }, { id: "a3", title: "합성 축 셋", code: "C" }])];
  serve((url, m) => {
    if (m === "POST" && url.endsWith("/decide")) { PEND = []; return json(200, { item_id: "p1", state: "kept", revision: 2, decided_at: null }); }
    if (url === "/api/axes") return OV_OK ? json(200, { ready: true, axes: AXES }) : json(500, { code: "INTERNAL" });
    if (url === "/api/collected?state=pending") return json(200, { ready: true, posts: PEND, counts: { pending: PEND.length, kept: 0 } });
    if (url === "/api/inbox?state=pending") return json(200, { entries: [], next_cursor: "", counts: { pending: 0 } });
    if (url === "/api/activities?limit=50") return json(200, { activities: [], next_cursor: "" });
    return json(404, {});
  });
});
afterEach(() => hideScreen());

test("막대 + 축 목록 — 대기 0 숨김 · 색 = 전체 순서 번호 · 누르면 축 화면 · 수집 인박스 위", async () => {
  const el = await show();
  const box = el.querySelector("#today-axes")!;
  expect(box.compareDocumentPosition(el.querySelector("#collected")!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(box.querySelector("h3")!.textContent).toBe("오늘의 축");
  const seg = [...box.querySelectorAll("[role=img] span")] as HTMLElement[];
  expect(seg.map(s => [s.style.flexGrow, s.style.background])).toEqual([["3", "var(--ax1)"], ["2", "var(--ax3)"]]);
  expect(box.querySelector("[role=img]")!.getAttribute("aria-label")).toBe("축별 대기 비율, 합 5");
  const links = [...box.querySelectorAll("li a")];
  expect(links.map(a => [a.getAttribute("href"), a.textContent])).toEqual([["#_me/axis/a1", "A합성 축 하나3"], ["#_me/axis/a3", "C합성 축 셋2"]]);
  expect(calls.filter(c => c.method !== "GET")).toEqual([]);
});

test("축 없음 · 대기 합 0 = 막대 없음 · 못 불러옴 = 한 줄", async () => {
  AXES = [];
  let el = await show();
  expect(el.querySelector("#today-axes")).toBeNull();
  hideScreen(); queryClient.clear();
  AXES = [ax("a1", "A", "합성 축 하나", 0)];
  el = await show();
  expect(el.querySelector("#today-axes")).toBeNull();
  expect(el.textContent).not.toContain("오늘의 축");
  hideScreen(); queryClient.clear();
  OV_OK = false;
  el = await show();
  expect(el.querySelector("#today-axes")).toBeNull();
  expect(el.textContent).toContain("오늘의 축을 불러오지 못했어요. 새로 고침해 주세요.");
  expect(el.querySelector("#collected")).not.toBeNull();   // 나머지는 그대로
});

test("수집 인박스 카드 = 축 코드 칩(여러 개 다, 코드 = 서버 값 또는 축 보기, 모르면 이름) · 보관 뒤 축 대기 수 다시 받기", async () => {
  const el = await show();
  const card = el.querySelector('li[data-id="p1"]')!;
  expect(text(card, ".axcode")).toEqual(["A", "모르는 축", "C"]);
  expect(card.querySelector(".axcode")!.getAttribute("title")).toBe("합성 축 하나");
  expect(ovCalls()).toBe(1);
  AXES = [ax("a1", "A", "합성 축 하나", 2), ax("a3", "C", "합성 축 셋", 2)];
  await click(byText(card, "button", "보관")[0]);
  expect(ovCalls()).toBe(2);
  expect(el.querySelector("#today-axes [role=img]")!.getAttribute("aria-label")).toBe("축별 대기 비율, 합 4");
});
