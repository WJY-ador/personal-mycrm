// 자동 분류 화면(2026-11-18 구조추천 명세 6.5) — 오브젝트 탭 머리 한 줄(담을 규칙 있는 오브젝트만) · 항목 페이지(자동 분류 표시, 근거 원문 = 글자 그대로,
// 고치기 없음, 동작 = [빼기] 하나, 확인 한 번 뒤 POST /api/route/exclude) · 나 탭 요약 추천 한 줄(서버 show 일 때만). 자료는 가짜 문장.
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { queryClient } from "../../shared/queries";
import { calls, click, installFetch, json, serve } from "../../test/fakeServer";
import { installMedia, JOURNAL, layout, meState, STATS } from "../../test/meFixture";
import { btns, hideMe, showMe } from "../../test/showMe";

const XSS = '<img src=x onerror="alert(1)"><script>alert(2)</script>';
const ROUTE = { v: 1, unit: "record", match: { source: "세션 정리" } };
const def = (id: string, key: string, label: string, o: object = {}) => ({ id, key, label, std_id: null, archived_at: null, semantic_kind: "event",
  fields: [{ key: "where_", label: "어디서", value_type: "text", options: [] }], ...o });
const it = (id: string, object_id: string, title: string, o: object = {}) => ({ id, object_id, code: null, title, body: "", data: { where_: XSS }, decision: null,
  revision: 1, semantic_kind: "event", proposal: null, links: [], created_at: "2026-11-01T01:00:00+00:00", updated_at: "2026-11-01T01:00:00+00:00", ...o });
const SRC = { record_id: "r_fake1", record_title: "P1. 가짜 피벗", unit_key: "", start: 0, end: 40 };
const base = meState();
const S = () => meState({
  definitions: [...base.definitions, def("od_pv", "pivots", "피벗", { policy: { route: ROUTE }, route_counts: { routed: 4, partial: 1, excluded: 0 } }),
    def("od_pl", "plain_notes", "그냥 메모")],
  items: [...base.items, it("i_auto", "od_pv", "P1. 가짜 피벗", { auto_routed: true, route_source: SRC }), it("i_hand", "od_pl", "손으로 쓴 메모")],
});
const page = (key: string) => ({ object: { id: "", key, label: "" }, columns: [], has_state: false, sort: { key: "title", dir: "asc" }, filters: [], total: 1, next_cursor: null,
  rows: [] });
let HINT = { show: false }, POSTED: { url: string; body: unknown }[] = [];

beforeEach(() => {
  installFetch(); installMedia(false); queryClient.clear(); HINT = { show: false }; POSTED = [];
  serve((url, m) => {
    if (m === "POST") { POSTED.push({ url, body: calls[calls.length - 1].body }); return json(200, { state: "excluded" }); }
    return url === "/api/me/layout" ? json(200, layout()) : url === "/api/me/stats" ? json(200, STATS) : url.startsWith("/api/journal") ? json(200, JOURNAL)
      : url.startsWith("/api/me/objects/") ? json(200, page(url.split("/").pop()!.split("?")[0]))
      : url.startsWith("/api/route/item") ? json(200, { item: { item_id: "i_auto", object_id: "od_pv", ...SRC, text: `**어디서** — ${XSS}\n줄 둘` } })
      : url === "/api/structure/hint" ? json(200, HINT) : json(200, { activities: [], activity_count: 0 });
  });
});
afterEach(() => { hideMe(); vi.unstubAllGlobals(); });

test("오브젝트 탭 머리 — 담을 규칙이 있는 오브젝트만 자동 분류, 분류 못 함 건수 한 줄", async () => {
  let el = await showMe("#_me/obj/pivots", S());
  expect(el.querySelector("#obj-route")!.textContent).toBe("자동 분류 4건, 분류 못 함 1건");
  hideMe();
  el = await showMe("#_me/obj/plain_notes", S());
  expect(el.querySelector("#obj-route")).toBeNull();
});

test("항목 페이지 — 자동 분류 표시, 근거 원문(기록 링크 + 단위 글을 글자 그대로), 고치기 없음, 동작은 [빼기] 하나", async () => {
  const el = await showMe("#_me/obj/pivots/i_auto", S());
  expect(el.querySelector("#home-detail")!.textContent).toContain("자동 분류");
  expect(calls.some(c => c.url === "/api/route/item?id=i_auto")).toBe(true);
  const src = el.querySelector("#route-src")!;
  expect(src.querySelector("dt")!.textContent).toBe("근거 원문");
  expect(src.querySelector("a")!.getAttribute("href")).toBe("#_me/journal/r_fake1");
  expect(src.querySelector("a")!.textContent).toBe("P1. 가짜 피벗");
  expect(src.querySelector("blockquote")!.textContent).toBe(`**어디서** — ${XSS}\n줄 둘`);   // 서식 해석 없이 글자 그대로
  expect(el.querySelector("#home-detail img, #home-detail script")).toBeNull();   // 원문과 필드의 태그는 요소가 되지 않는다
  expect(el.querySelector('#home-detail [title="눌러서 고치기"]')).toBeNull();   // 고치기 숨김(제목, 본문 인라인 편집 없음)
  expect(btns(el)).toEqual(["빼기"]);   // 휴지통 켜짐이어도 [삭제] 없음
});

test("[빼기] — 확인 취소 = 요청 0, 확인 = POST /api/route/exclude {item_id, expected_revision} 뒤 목록으로", async () => {
  const el = await showMe("#_me/obj/pivots/i_auto", S());
  const ask = vi.fn(() => false);
  vi.stubGlobal("confirm", ask);
  await click([...el.querySelectorAll(".hacts button")].find(b => b.textContent === "빼기"));
  expect(ask).toHaveBeenCalledTimes(1);
  expect(POSTED).toEqual([]);
  ask.mockReturnValue(true);
  await click([...el.querySelectorAll(".hacts button")].find(b => b.textContent === "빼기"));
  expect(POSTED).toEqual([{ url: "/api/route/exclude", body: { item_id: "i_auto", expected_revision: 1 } }]);
  expect(location.hash).toBe("#_me/obj/pivots");
});

test("손으로 만든 항목 — 자동 분류 표시, 근거 원문 없음, 고치기와 [삭제] 그대로", async () => {
  const el = await showMe("#_me/obj/plain_notes/i_hand", S());
  expect(el.querySelector("#route-src")).toBeNull();
  expect(el.querySelector("#home-detail")!.textContent).not.toContain("자동 분류");
  expect(el.querySelector('#home-detail [title="눌러서 고치기"]')).not.toBeNull();
  expect(btns(el)).toEqual(["삭제"]);
  expect(calls.some(c => c.url.startsWith("/api/route/item"))).toBe(false);
});

test("나 탭 요약 — 서버 show 일 때만 추천할 구조가 있어요 한 줄(내 구조 설정으로)", async () => {
  let el = await showMe("#_me/summary", S());
  expect(el.querySelector("#reco-hint")).toBeNull();
  hideMe(); queryClient.clear(); HINT = { show: true };
  el = await showMe("#_me/summary", S());
  const a = el.querySelector("#reco-hint a")!;
  expect([a.textContent, a.getAttribute("href")]).toEqual(["추천할 구조가 있어요", "#_setup/structure"]);
});
