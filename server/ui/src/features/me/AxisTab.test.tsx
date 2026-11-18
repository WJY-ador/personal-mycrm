// 「나」 축 탭(축 잇기, 2026-11-18 명세 4.1) — #_me/axis = 축 카드 목록(넘기지 않는다) · 카드 = 축 화면 링크 ·
// 축 화면 = 머리(코드, 이름, 대기·보관) · [한 장](AI 초안 한 줄 + 시각, 웹 대화 답 렌더러, 「# 」 머리 떼기, 태그는 글자 그대로) ·
// 한 장 없음(page null, 404) = 한 줄 · 수집 글 = 목록 보기에 축 필터(대기 먼저) · 행 축 코드 칩 · 접힌 관점과 키워드 안 = 기존 항목 상세 · 쓰기 0.
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { queryClient } from "../../shared/queries";
import { calls, installFetch, json, serve, text } from "../../test/fakeServer";
import { installMedia, JOURNAL, layout, meState, STATS } from "../../test/meFixture";
import { hideMe, showMe } from "../../test/showMe";

// 서버 꼴(GET /api/axes, imports.axis_overview) 그대로
const ax = (id: string, code: string, title: string, o: object = {}) => ({ id, code, title, description: "", keywords: [], counts: { pending: 0, kept: 0, total: 0 }, page: null, ...o });
const PG = { record_id: "r_pg", title: "한 장", at: "2026-11-18T05:00:00+00:00", ai: true, notice: "AI 가 쓴 초안이에요. 판단 근거가 아니에요." };
const OV = () => ({
  ready: true,
  axes: [ax("a1", "A", "합성 축 하나", { description: "합성 관점", keywords: ["합성어", "kw"], counts: { pending: 3, kept: 1, total: 5 }, page: PG }), ax("a2", "B-1", "합성 축 둘")],
});
const MD = "# A. 합성 축 하나 — 나에 대해 한 장\n\n첫 문단 **굵게** <script>alert(1)</script>\n\n## 아직 답하지 못한 것\n\n- <b>물음</b>\n";
const row = (id: string, title: string, state: string, axes: unknown) => ({ id, code: null, title, revision: 1, updated_at: "2026-11-01T01:00:00+00:00", data: {}, state, axes });
const LIST = { object: { id: "od_cp", key: "collected_posts", label: "수집 글" }, columns: [], has_state: true, sort: { key: "state", dir: "desc" },
  filters: [], states: { pending: 1, kept: 1, dropped: 0 }, total: 2, next_cursor: null,
  rows: [row("c1", "합성 글 하나", "pending", [{ id: "a1", code: "A", title: "합성 축 하나" }, { id: "a2", code: "B-1", title: "합성 축 둘" }]), row("c2", "합성 글 둘", "kept", [])] };
const def = (id: string, key: string, label: string) => ({ id, key, label, std_id: null, archived_at: null, fields: [] });
const S = () => { const b = meState(); return meState({ definitions: [...b.definitions, def("od_cp", "collected_posts", "수집 글")] }); };
const ONE = () => json(200, { ready: true, axes: [{ ...OV().axes[0], page: { ...PG, body: MD } }] });
let OVR: () => Response = () => json(200, OV()), PAGE: () => Response = ONE;

beforeEach(() => {
  installFetch(); installMedia(false); queryClient.clear();
  OVR = () => json(200, OV());
  PAGE = ONE;
  serve(url => (url === "/api/me/layout" ? json(200, layout()) : url === "/api/me/stats" ? json(200, STATS) : url.startsWith("/api/journal") ? json(200, JOURNAL)
    : url === "/api/axes" ? OVR() : url.startsWith("/api/axes?id=") ? PAGE()
    : url.startsWith("/api/me/objects/") ? json(200, LIST) : json(200, { activities: [], activity_count: 0 })));
});
afterEach(() => { hideMe(); vi.unstubAllGlobals(); });
const urls = (p: string) => calls.filter(c => c.url.startsWith(p)).map(c => c.url);

test("축 카드 목록 — 넘기지 않는다 · 코드, 이름, 대기, 보관, 한 장 있음 · 카드 = 축 화면 링크 · 한 장 조회 0", async () => {
  const el = await showMe("#_me/axis", S());
  expect(location.hash).toBe("#_me/axis");
  const cards = [...el.querySelectorAll("#axis-list li a")];
  expect(cards.map(a => a.getAttribute("href"))).toEqual(["#_me/axis/a1", "#_me/axis/a2"]);
  expect(cards.map(a => a.textContent)).toEqual(["A합성 축 하나대기 3보관 1한 장 있음", "B-1합성 축 둘대기 0보관 0"]);
  expect((cards[1].querySelector("i") as HTMLElement).style.background).toBe("var(--ax2)");
  expect(urls("/api/axes?")).toEqual([]);
  expect(calls.filter(c => c.method !== "GET")).toEqual([]);
});

test("축 화면 — 머리 · 한 장(AI 초안 한 줄 + 시각, 렌더러, 「# 」 머리 뗌, 태그 글자 그대로) · 수집 글 축 필터(f.axes) 대기 먼저 · 칩(서버 행 axes) · 쓰기 0", async () => {
  const el = await showMe("#_me/axis/a1", S());
  expect(location.hash).toBe("#_me/axis/a1");
  expect(el.querySelector("#axis-h")!.textContent).toBe("A합성 축 하나");
  expect(urls("/api/axes?")).toEqual(["/api/axes?id=a1"]);
  const doc = el.querySelector("#axis-doc")!;
  expect(doc.querySelector("#axis-ai")!.textContent).toMatch(/^AI가 쓴 초안이에요\. 판단 근거가 아니에요\.11월 18일 \d\d:00 갱신$/);
  expect(doc.textContent).not.toContain("# A.");                       // 머리 한 줄은 뗀다(화면 머리가 대신)
  expect(text(doc, "h3")).toEqual(["한 장", "아직 답하지 못한 것"]);    // 「## 」 = 렌더러 소제목
  expect(text(doc, "strong")).toEqual(["굵게"]);
  expect(doc.querySelector("script, b")).toBeNull();                   // 태그는 글자 그대로
  expect(doc.textContent).toContain("<script>alert(1)</script>");
  expect(text(doc, "li")).toEqual(["<b>물음</b>"]);
  expect(urls("/api/me/objects/")).toEqual(["/api/me/objects/collected_posts?sort=state&dir=desc&f.axes=a1"]);
  const chips = [...el.querySelectorAll("#obj-list tbody tr")].map(r => text(r, ".axcode"));
  expect(chips).toEqual([["A", "B-1"], []]);
  expect(el.querySelector("#obj-list .axcode")!.getAttribute("title")).toBe("합성 축 하나");
  expect(calls.filter(c => c.method !== "GET")).toEqual([]);
});

test("접힌 「원하는 관점과 키워드」 — 키워드 칩 + 기존 항목 상세(삭제 버튼 그대로)", async () => {
  const el = await showMe("#_me/axis/a1", { ...S(), switches: { trash: true } });
  const fold = el.querySelector("details")!;
  expect(fold.open).toBe(false);
  expect(fold.querySelector("summary")!.textContent).toBe("원하는 관점과 키워드");
  expect(text(fold, ".chip")).toEqual(["합성어", "kw"]);
  expect(fold.querySelector("#home-detail h2")!.textContent).toContain("고객 이해");
  expect(text(fold, ".hacts button")).toEqual(["삭제"]);
});

test("한 장 없음 — page null = 한 줄, 한 장 조회 0 · 축 하나 조회가 404 NOT-FOUND = 같은 한 줄(실패 아님)", async () => {
  let el = await showMe("#_me/axis/a2", S());
  expect(el.querySelector("#axis-nopage")!.textContent).toBe("아직 한 장이 없어요.");
  expect(el.querySelector("#axis-ai")).toBeNull();
  expect(urls("/api/axes?")).toEqual([]);
  hideMe(); queryClient.clear();
  PAGE = () => json(404, { code: "NOT-FOUND", msg: "없어요" });
  el = await showMe("#_me/axis/a1", S());
  expect(el.querySelector("#axis-nopage")!.textContent).toBe("아직 한 장이 없어요.");
  expect(el.querySelector("#axis-doc .partfail")).toBeNull();
});

test("축 보기 실패 — 카드 목록 = 실패 안내 · 축 화면은 항목 상세로 남고 한 장 = 실패 안내, 수집 글 목록은 그대로", async () => {
  OVR = () => json(500, { code: "INTERNAL", msg: "x" });
  let el = await showMe("#_me/axis", S());
  expect(el.querySelector("#axis-list .partfail")!.textContent).toContain("축을 불러오지 못했어요.");
  hideMe(); queryClient.clear();
  el = await showMe("#_me/axis/a1", S());
  expect(el.querySelector("#axis-h")!.textContent).toBe("고객 이해");
  expect(el.querySelector("#axis-doc .partfail")!.textContent).toContain("한 장을 불러오지 못했어요.");
  expect(urls("/api/me/objects/")).toEqual(["/api/me/objects/collected_posts?sort=state&dir=desc&f.axes=a1"]);
});
