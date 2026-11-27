// API 견본 대조(TS 쪽) — 축 보기(GET /api/axes) · 축 하나 + 한 장 본문(GET /api/axes?id=) · 수집 글 행 축(목록 보기 rows[].axes).
// 서버 꼴(Raw*)을 화면 꼴로 바꾸는 곳은 axesApi 하나 — 그 바꿈도 여기서 본다.
import { afterEach, expect, test, vi } from "vitest";
import { axesApi, type RawAxes, type AxisRef } from "./axes";
import sample from "./axes.sample.json";

const typed = sample satisfies { overview: RawAxes; one: RawAxes; row_axes: AxisRef[] };
const reply = (j: unknown) => vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(j), { status: 200, headers: { "content-type": "application/json" } })));
afterEach(() => vi.unstubAllGlobals());

test("견본 = 축 보기 · 축 하나(한 장 본문) · 행 축", () => {
  expect(typed.overview.axes.map(a => a.code)).toEqual(["A", "B-1"]);
  expect(typed.overview.axes[1].page).toBeNull();
  expect(typed.one.axes[0].page!.body!.startsWith("# ")).toBe(true);
});

test("서버 꼴 → 화면 꼴(axesApi 한 곳)", async () => {
  reply(sample.overview);
  const o = await axesApi.overview();
  expect(o.axes[0]).toEqual({ item_id: "i_axis_a", code: "A", title: "견본 축 하나", body: "견본 관점 문장", keywords: ["견본어", "sample"],
    pending: 3, kept: 1, total: 5, page: { record_id: "r_page_a", updated_at: "2026-11-18T05:00:00+00:00" },
    topics: [{ item_id: "i_topic_a", title: "견본 주제", records: 3, last_on: "2026-11-20" }] });
  expect(o.axes[1].page).toBeNull();
  expect(o.axes[1].topics).toEqual([]);
  reply(sample.one);
  expect(await axesApi.page("i_axis_a")).toEqual({ record_id: "r_page_a", updated_at: "2026-11-18T05:00:00+00:00", markdown: sample.one.axes[0].page.body,
    mine: sample.one.axes[0].page.mine, ai_newer: true, ai: { at: "2026-11-18T05:00:00+00:00", markdown: sample.one.axes[0].page.ai_body } });
  reply(sample.overview);   // 본문 없는 응답 = 한 장 없음
  expect(await axesApi.page("i_axis_b1")).toBeNull();
});
