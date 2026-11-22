// 수집 인박스 요약 상자(2026-11-22 구현계획 4-1) — AI 표시 + 「시각 기준 대기 N건 요약」 · 주제 줄(굵은 이름, 한 문장, 지금 대기 글 수) ·
// 주제 누르기 = 그 글만, 다시 누르기 = 풀림 · 축 칩(대기, 신호) 누르기 = 그 축 글만 · 요약 뒤 새 글 한 줄 · 요약 없음 · 못 불러와도 인박스는 그대로.
import { afterEach, beforeEach, expect, test } from "vitest";
import { queryClient } from "../../shared/queries";
import { click, installFetch, json, serve, text } from "../../test/fakeServer";
import { installMedia } from "../../test/meFixture";
import { hideScreen, showScreen } from "../../test/showScreen";
import sample from "./digest.sample.json";

type P = Record<string, unknown>;
const post = (id: string, grade: string | null, axes: P[] = []): P => ({
  id, revision: 1, title: `${id} 제목 줄`, channel: "linkedin", author_display: `${id} 작성자`, post_url: `https://x.example/${id}`, posted_on: "2026-11-10",
  collected_on: "2026-11-12", axes, ai: { grade, summary: null, as_is: null, to_be: null, ops: null, points: null }, state: "pending", decided_by: null, decided_at: null });
const A = { id: "ax1", code: "A", title: "가짜 축" };
const PEND = [post("p1", "signal", [A]), post("p2", "news"), post("p3", "news", [A])];
const WITH = () => ({ ...structuredClone(sample.with), pending_n: 3, new_since: 1,
  digest: { themes: [{ name: "가짜 주제 하나", line: "가짜 글 둘이 같은 말을 해요.", item_ids: ["p1", "p2", "gone"] }, { name: "가짜 주제 둘", line: "가짜 한 문장.", item_ids: ["p3"] }],
    input_n: 2, made_at: "2026-11-22T00:00:00+00:00" },
  by_axis: [{ code: "A", title: "가짜 축", item_id: "ax1", pending: 2, signal: 1 }, { code: "B", title: "빈 축", item_id: "ax2", pending: 0, signal: 0 }] });
let DIG: () => Response = () => json(200, WITH());
const S = { user: { nav: "new" }, switches: {}, activity_ui: { actions: {}, providers: {}, pending_days: 30 }, inbox: { pending: 0 }, journal: [] };
const show = () => showScreen("today", "#_today", ["today", "", ""], S);
const cards = (el: Element) => [...el.querySelectorAll("#collected li[data-id]")].map(li => li.getAttribute("data-id"));

beforeEach(() => {
  installFetch(); installMedia(false); queryClient.clear(); DIG = () => json(200, WITH());
  serve(url => {
    if (url === "/api/collected/digest") return DIG();
    if (url === "/api/collected?state=pending") return json(200, { ready: true, posts: PEND, counts: { pending: 3, kept: 0 } });
    if (url === "/api/inbox?state=pending") return json(200, { entries: [], next_cursor: "", counts: { pending: 0 } });
    if (url === "/api/activities?limit=50") return json(200, { activities: [], next_cursor: "" });
    if (url === "/api/axes") return json(200, { ready: true, axes: [] });
    return json(404, {});
  });
});
afterEach(() => hideScreen());

test("요약 있음 — 머리(AI 표시, 기준 시각, 대기 N건 요약) · 새로 N건 · 주제 줄 = 이름 + 문장 + 지금 대기 글 수 · 대기 0 축은 숨김", async () => {
  const el = await show();
  const d = el.querySelector("#digest")!;
  expect(d.querySelector(".chip.o-ai")).not.toBeNull();
  expect(d.textContent).toContain("기준 대기 2건 요약");
  expect(el.querySelector("#digest-new")!.textContent).toBe("요약 뒤 새로 1건. 요약은 다음 동기화에서 갱신해요.");
  expect(text(d, "ul button")).toEqual(["가짜 주제 하나가짜 글 둘이 같은 말을 해요.2", "가짜 주제 둘가짜 한 문장.1"]);   // 없는 글(gone)은 세지 않는다
  expect(text(d, "[role=group] button")).toEqual(["A대기 2신호 1"]);
});

test("주제 누르기 = 그 글만, 다시 누르기 = 풀림 · 축 칩 = 그 축 글만(주제 고름은 풀린다)", async () => {
  const el = await show();
  expect(cards(el).sort()).toEqual(["p1", "p2", "p3"]);
  const th = el.querySelector("#digest ul button")!;
  await click(th);
  expect(th.getAttribute("aria-pressed")).toBe("true");
  expect(cards(el).sort()).toEqual(["p1", "p2"]);
  await click(th);
  expect(cards(el).sort()).toEqual(["p1", "p2", "p3"]);
  await click(th);
  await click(el.querySelector("#digest [role=group] button"));
  expect(cards(el).sort()).toEqual(["p1", "p3"]);
  expect(th.getAttribute("aria-pressed")).toBe("false");
});

test("요약 없음 = 한 줄(대기 수) + 축 칩은 그대로 · 못 불러오면 한 줄, 인박스는 보인다", async () => {
  DIG = () => json(200, { ...WITH(), digest: null, new_since: 3 });
  let el = await show();
  expect(el.querySelector("#digest-none")!.textContent).toBe("아직 요약이 없어요. 대기 3건, 다음 동기화에서 만들어요.");
  expect(el.querySelector("#digest .chip.o-ai")).toBeNull();
  expect(text(el, "#digest [role=group] button")).toHaveLength(1);
  hideScreen(); queryClient.clear();
  DIG = () => json(500, { code: "X", msg: "" });
  el = await show();
  expect(el.querySelector("#digest")).toBeNull();
  expect(el.querySelector("#collected")!.textContent).toContain("인박스 요약을 불러오지 못했어요");
  expect(cards(el)).toHaveLength(3);
});
