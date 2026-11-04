// 「나」 커스텀 탭 — 묶음 선택 상자 하나: 처음엔 첫 묶음 · 바꾸면 목록 교체 · 묶음 1개면 상자 없음 · 열린 항목의 묶음으로 따라감 · 머리 총개수 그대로 · 저장 요청 0.
import { act } from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { queryClient } from "../../shared/queries";
import { calls, flush, installFetch, json, serve, text } from "../../test/fakeServer";
import { installMedia, JOURNAL, layout, meState, STATS } from "../../test/meFixture";
import { hideMe, showMe } from "../../test/showMe";

beforeEach(() => {
  installFetch(); installMedia(false); queryClient.clear();
  serve(url => (url === "/api/me/layout" ? json(200, layout()) : url === "/api/me/stats" ? json(200, STATS) : url.startsWith("/api/journal") ? json(200, JOURNAL) : json(200, { activities: [], activity_count: 0 })));
});
afterEach(() => { hideMe(); vi.unstubAllGlobals(); });

const it = (id: string, object_id: string, title: string, code: string) => ({ id, object_id, code, title, body: "", data: {}, decision: null, revision: 1, semantic_kind: "collection",
  proposal: null, links: [], created_at: "2026-10-01T01:00:00+00:00", updated_at: "2026-10-01T01:00:00+00:00" });
const def = (id: string, label: string) => ({ id, key: id, label, std_id: null, archived_at: null, fields: [] });
const base = meState();
const two = () => meState({
  definitions: [...base.definitions, def("od_c1", "기준"), def("od_c2", "접근 방식")],
  items: [...base.items, it("c1", "od_c1", "정본이 먼저", "C-01"), it("c2", "od_c1", "조직을 맞춘다", "C-03"), it("m1", "od_c2", "작게 시작", "M-01")],
});
const one = () => meState({ definitions: [...base.definitions, def("od_c1", "기준")], items: [...base.items, it("c1", "od_c1", "정본이 먼저", "C-01")] });
const sel = (el: Element) => el.querySelector<HTMLSelectElement>("select[aria-label='묶음 고르기']");
const titles = (el: Element) => text(el, "#home-list li a .ht");
async function choose(s: HTMLSelectElement, v: string) {
  await act(async () => { Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value")!.set!.call(s, v); s.dispatchEvent(new Event("change", { bubbles: true })); });
  await flush();
}

test("묶음 둘 이상 — 처음엔 첫 묶음 · 옵션 = 묶음 이름 + 개수 · 고르면 그 묶음 목록으로 교체 · 총개수는 그대로", async () => {
  const el = await showMe("#_me/custom/c1", two());
  expect(text(el, "#home-list option")).toEqual(["기준 2", "접근 방식 1"]);
  expect(sel(el)!.value).toBe("od_c1");
  expect(titles(el)).toEqual(["C-01 정본이 먼저", "C-03 조직을 맞춘다"]);
  expect(el.querySelector("#home-list .htools .count")!.textContent).toBe("3");
  await choose(sel(el)!, "od_c2");
  expect(titles(el)).toEqual(["M-01 작게 시작"]);
  expect(el.querySelector("#home-list .htools .count")!.textContent).toBe("3");
  expect(calls.filter(c => c.method !== "GET")).toEqual([]);
});

test("묶음 하나 — 선택 상자 없이 그 목록만", async () => {
  const el = await showMe("#_me/custom/c1", one());
  expect(sel(el)).toBeNull();
  expect(titles(el)).toEqual(["C-01 정본이 먼저"]);
});

test("열린 항목이 다른 묶음이면 그 묶음을 보여 준다 · 항목이 바뀌면 그 묶음으로 따라간다", async () => {
  let el = await showMe("#_me/custom/m1", two());
  expect(sel(el)!.value).toBe("od_c2");
  expect(titles(el)).toEqual(["M-01 작게 시작"]);
  el = await showMe("#_me/custom/c2", two());
  expect(sel(el)!.value).toBe("od_c1");
  expect(titles(el)).toEqual(["C-01 정본이 먼저", "C-03 조직을 맞춘다"]);
});
