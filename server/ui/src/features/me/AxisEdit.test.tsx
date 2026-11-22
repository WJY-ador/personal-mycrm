// 축 한 장 그 자리 편집(2026-11-22 구현계획 2절, 3절) — 두 번 누르기/포커스+Enter = 원문 그대로 편집 상자 · Esc = 취소(요청 0) ·
// Cmd/Ctrl+Enter = 받은 그대로 저장(expected_updated_at) · 바깥 누르기 = 바뀌었을 때만 저장 · STALE = 글 남김 ·
// 내 판 머리 「내가 고친 판」 · 새 AI 초안 접힌 한 줄 · 사례 짝 지어 접힘 + 라벨 표. 문장은 모두 가짜.
import { act } from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { queryClient } from "../../shared/queries";
import { calls, click, flush, installFetch, json, serve, text } from "../../test/fakeServer";
import { installMedia, JOURNAL, layout, meState, STATS } from "../../test/meFixture";
import { hideMe, showMe, type } from "../../test/showMe";

const MD = "# A. 가짜 축 — 한 장\n\n## 순서를 먼저\n\n본문 하나.\n\n## 사례로 다시 보기\n\n### 순서를 먼저\n\n**그때 상황** 도구가 셋.\n\n**남은 기준** 순서 먼저.\n";
const PG = { record_id: "r_pg", title: "한 장", at: "2026-11-18T05:00:00+00:00", ai: true, notice: "" };
const AX = (page: object | null) => ({ ready: true, axes: [{ id: "a1", code: "A", title: "가짜 축", description: "", keywords: [], counts: { pending: 0, kept: 0, total: 0 }, page }] });
let PAGE: () => object = () => AX({ ...PG, body: MD }), POST: () => Response = () => json(200, { mine: { record_id: "r_m", updated_at: "2026-11-22T01:00:00+00:00" } });

beforeEach(() => {
  installFetch(); installMedia(false); queryClient.clear();
  PAGE = () => AX({ ...PG, body: MD });
  POST = () => json(200, { mine: { record_id: "r_m", updated_at: "2026-11-22T01:00:00+00:00" } });
  serve((url, method) => (url === "/api/me/layout" ? json(200, layout()) : url === "/api/me/stats" ? json(200, STATS) : url.startsWith("/api/journal") ? json(200, JOURNAL)
    : url === "/api/axes" ? json(200, AX(PG)) : url.startsWith("/api/axes?id=") ? json(200, PAGE())
    : method === "POST" && url === "/api/axes/a1/page" ? POST() : json(200, { activities: [], activity_count: 0, rows: [], columns: [], filters: [], total: 0 })));
});
afterEach(() => { hideMe(); vi.unstubAllGlobals(); });
const posts = () => calls.filter(c => c.method === "POST");
const key = async (el: Element, k: string, o: KeyboardEventInit = {}) => { await act(async () => { el.dispatchEvent(new KeyboardEvent("keydown", { key: k, bubbles: true, ...o })); }); await flush(); };
const dbl = async (el: Element) => { await act(async () => { el.dispatchEvent(new MouseEvent("dblclick", { bubbles: true })); }); await flush(); };
const doc = (el: Element) => el.querySelector("#axis-doc [tabindex='0']")!;

test("사례 짝 — 위 절 끝에 접힌 「사례」, 라벨 | 내용 표 · 사례 절 제목은 그리지 않는다 · AI 표시 머리", async () => {
  const el = await showMe("#_me/axis/a1", meState());
  expect(el.querySelector("#axis-ai")).not.toBeNull();
  const c = el.querySelector("#axis-doc details")!;
  expect(c.querySelector("summary")!.textContent).toBe("사례순서를 먼저");
  expect(text(c, "th")).toEqual(["그때 상황", "남은 기준"]);
  expect(el.querySelector("#axis-doc")!.textContent).not.toContain("사례로 다시 보기");
});

test("두 번 누르기 = 원문 그대로 상자 + 안내 · Esc = 취소(요청 0) · 포커스 + Enter 도 같다", async () => {
  const el = await showMe("#_me/axis/a1", meState());
  await dbl(doc(el).querySelector("p")!);
  const ta = el.querySelector("#axis-edit textarea") as HTMLTextAreaElement;
  expect(ta.value).toBe(MD);
  expect(el.querySelector("#axis-edit-hint")!.textContent).toBe("저장 Cmd+Enter · 취소 Esc");
  await key(ta, "Escape");
  expect(el.querySelector("#axis-edit")).toBeNull();
  await key(doc(el), "Enter");
  expect(el.querySelector("#axis-edit textarea")).not.toBeNull();
  await key(el.querySelector("#axis-edit textarea")!, "Escape");
  expect(posts()).toEqual([]);
});

test("Cmd+Enter = 받은 그대로 저장(처음 = expected null) · 한글 조합 중 Enter 무시 · 바깥 누르기는 안 바뀌면 요청 0", async () => {
  const el = await showMe("#_me/axis/a1", meState());
  await key(doc(el), "Enter");
  await act(async () => { document.body.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true })); }); await flush();
  expect(el.querySelector("#axis-edit")).toBeNull();
  expect(posts()).toEqual([]);
  await key(doc(el), "Enter");
  const ta = el.querySelector("#axis-edit textarea") as HTMLTextAreaElement;
  await type(ta, "  고친 글 그대로  ");
  await key(ta, "Enter", { metaKey: true, isComposing: true });
  expect(posts()).toEqual([]);
  await key(ta, "Enter", { ctrlKey: true });
  expect(posts()).toEqual([{ url: "/api/axes/a1/page", method: "POST", body: { markdown: "  고친 글 그대로  ", expected_updated_at: null } }]);
  expect(el.querySelector("#axis-edit")).toBeNull();
});

test("바깥 누르기 = 바뀌었으면 저장 · STALE = 글 남기고 한 줄", async () => {
  PAGE = () => AX({ ...PG, body: MD, mine: { record_id: "r_m", updated_at: "2026-11-21T01:00:00+00:00" }, ai_newer: false });
  POST = () => json(409, { code: "STALE", msg: "" });
  const el = await showMe("#_me/axis/a1", meState());
  await key(doc(el), "Enter");
  const ta = el.querySelector("#axis-edit textarea") as HTMLTextAreaElement;
  await type(ta, "바뀐 글");
  await act(async () => { document.body.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true })); }); await flush();
  expect(posts().map(c => c.body)).toEqual([{ markdown: "바뀐 글", expected_updated_at: "2026-11-21T01:00:00+00:00" }]);
  expect((el.querySelector("#axis-edit textarea") as HTMLTextAreaElement).value).toBe("바뀐 글");
  expect(el.querySelector("#axis-edit-err")!.textContent).toContain("다른 곳에서 먼저 바뀌었어요");
});

test("내 판 = 「내가 고친 판」 머리(AI 표시 없음) · 새 AI 초안 = 접힌 한 줄, 펼치면 AI 초안 본문", async () => {
  PAGE = () => AX({ ...PG, body: "# 머리\n\n내가 고친 문단.", mine: { record_id: "r_m", updated_at: "2026-11-21T01:00:00+00:00" }, ai_newer: true, ai_body: "# 머리\n\nAI 새 문단." });
  const el = await showMe("#_me/axis/a1", meState());
  expect(el.querySelector("#axis-mine")!.textContent).toMatch(/^내가 고친 판 · /);
  expect(el.querySelector("#axis-ai")).toBeNull();
  const nw = el.querySelector("#axis-newer") as HTMLDetailsElement;
  expect(nw.querySelector("summary")!.textContent).toMatch(/^새 AI 초안이 왔어요\(/);
  expect(nw.textContent).toContain("AI 새 문단.");
  expect(doc(el).textContent).toContain("내가 고친 문단.");
  await click(nw.querySelector("summary"));
  expect(nw.open).toBe(true);
});
