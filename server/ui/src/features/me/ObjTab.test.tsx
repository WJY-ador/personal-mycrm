// 「나」 오브젝트 탭(2026-11-18 명세 1절) — 사용자 오브젝트마다 하위 탭(커스텀 탭 없음) · 목록 보기(열·정렬·칩·검색·더 보기, 서버가 거른다)
// · 항목 페이지(필드 전부, AI 필드 「AI 요약」) · 옛 #_me/custom 주소 넘김 · 좁은 화면 카드 · 종류별 건수 오브젝트마다 한 칸 · 쓰기 0.
import { act } from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { queryClient } from "../../shared/queries";
import { calls, click, flush, installFetch, json, serve, text } from "../../test/fakeServer";
import { installMedia, JOURNAL, layout, meState, STATS } from "../../test/meFixture";
import { hideMe, showMe, type } from "../../test/showMe";

const CH = [{ value: "linkedin", label: "LinkedIn" }, { value: "reddit", label: "Reddit" }];
const def = (id: string, key: string, label: string, fields: object[] = []) => ({ id, key, label, std_id: null, archived_at: null, fields });
const it = (id: string, object_id: string, title: string, data: object = {}) => ({ id, object_id, code: null, title, body: "", data, decision: null, revision: 1,
  semantic_kind: "collection", proposal: null, links: [], created_at: "2026-11-01T01:00:00+00:00", updated_at: "2026-11-01T01:00:00+00:00" });
const FIELDS = [{ key: "channel", label: "채널", value_type: "select", options: CH }, { key: "author_display", label: "작성자", value_type: "text", options: [] },
  { key: "posted_on", label: "게시일", value_type: "date", options: [] }, { key: "post_url", label: "원 URL", value_type: "text", options: [] }, { key: "ai_summary", label: "AI 요약문", value_type: "text", options: [] }];
const base = meState();
const S = () => meState({
  definitions: [...base.definitions, def("od_cp", "collected_posts", "수집 글", FIELDS), def("od_vr", "verified_results", "확인된 결과")],
  items: [...base.items, it("c1", "od_cp", "합성 글 하나", { channel: "reddit", author_display: "작성자 갑", posted_on: "2026-11-10", ai_summary: "합성 요약" }),
    it("c2", "od_cp", "합성 글 둘", { channel: "linkedin" }), it("v1", "od_vr", "합성 결과")],
});
const COLS = FIELDS.slice(0, 4);
const row = (id: string, title: string, data: object, state = "pending") => ({ id, code: null, title, revision: 1, updated_at: "2026-11-01T01:00:00+00:00", data, state });
const page = (o: object = {}) => ({ object: { id: "od_cp", key: "collected_posts", label: "수집 글" }, columns: COLS, has_state: true, sort: { key: "posted_on", dir: "desc" },
  filters: [{ key: "channel", label: "채널", values: [{ value: "linkedin", label: "LinkedIn", n: 1 }, { value: "reddit", label: "Reddit", n: 1 }] }],
  states: { pending: 1, kept: 1, dropped: 0 }, total: 2, next_cursor: null,
  rows: [row("c1", "합성 글 하나", { channel: "reddit", author_display: "작성자 갑", posted_on: "2026-11-10", post_url: "https://example.com/a/very/long/path" }, "kept"),
    row("c2", "합성 글 둘", { channel: "linkedin", post_url: "javascript:alert(1)" })], ...o });
let LIST: (url: string) => object = () => page();

beforeEach(() => {
  installFetch(); installMedia(false); queryClient.clear(); LIST = () => page();
  serve(url => (url === "/api/me/layout" ? json(200, layout()) : url === "/api/me/stats" ? json(200, STATS) : url.startsWith("/api/journal") ? json(200, JOURNAL)
    : url.startsWith("/api/me/objects/") ? json(200, LIST(url)) : json(200, { activities: [], activity_count: 0 })));
});
afterEach(() => { hideMe(); vi.unstubAllGlobals(); });
const lists = () => calls.filter(c => c.url.startsWith("/api/me/objects/")).map(c => c.url);

test("하위 탭 — 오브젝트마다 하나(이름 = label, 사람·출처 앞, 건수 = 항목 수) · 커스텀 탭 없음", async () => {
  const el = await showMe("#_me/summary", S());
  expect(text(el, "nav a").map(t => t!.replace(/\d/g, ""))).toEqual(["요약", "기준", "결정", "축", "수집 글", "확인된 결과", "사람", "출처"]);
  expect([...el.querySelectorAll("nav a")].map(a => a.getAttribute("href")).slice(4, 6)).toEqual(["#_me/obj/collected_posts", "#_me/obj/verified_results"]);
  expect(text(el, "nav a")[4]).toBe("수집 글2");
  // 종류별 건수 — 오브젝트마다 한 칸, 그 탭으로
  const kinds = [...el.querySelectorAll("#me-summary li a")].map(a => [a.textContent, a.getAttribute("href")]);
  expect(kinds).toContainEqual(["수집 글", "#_me/obj/collected_posts"]);
  expect(kinds).toContainEqual(["확인된 결과", "#_me/obj/verified_results"]);
  expect(el.textContent).not.toContain("커스텀");
});

test("목록 보기 — 열(제목 + 필드 + 상태) · 값 표시(선택지 이름·날짜·상태 낱말) · 행 = 항목 페이지 링크 · 칩 · 쓰기 0", async () => {
  const el = await showMe("#_me/obj/collected_posts", S());
  expect(lists()).toEqual(["/api/me/objects/collected_posts"]);
  expect(text(el, "#obj-list th")).toEqual(["제목", "채널", "작성자", "게시일 ▼", "원 URL", "상태"]);
  expect(el.querySelector("#obj-list th[aria-sort=descending]")!.textContent).toBe("게시일 ▼");
  expect([...el.querySelectorAll("#obj-list tbody tr")].map(r => text(r, "td"))).toEqual([["합성 글 하나", "Reddit", "작성자 갑", "11월 10일", "원문", "보관"], ["합성 글 둘", "LinkedIn", "", "", "", "대기"]]);
  const link = el.querySelector<HTMLAnchorElement>("#obj-list tbody td a[target=_blank]")!;
  expect([link.getAttribute("href"), link.rel, link.textContent]).toEqual(["https://example.com/a/very/long/path", "noopener noreferrer", "원문"]);   // 긴 주소 대신 한 낱말
  expect(el.querySelectorAll("#obj-list tbody td a[target=_blank]").length).toBe(1);   // http(s) 아닌 값은 링크 없음
  expect(el.querySelector("#obj-list tbody a")!.getAttribute("href")).toBe("#_me/obj/collected_posts/c1");
  expect(text(el, "#obj-list [role=group]")).toEqual(["상태대기 1보관 1", "채널LinkedIn 1Reddit 1"]);   // 0건 칩(버림)은 숨김
  expect(calls.filter(c => c.method !== "GET")).toEqual([]);
});

test("칩·정렬·검색·더 보기 = 서버에 다시 묻는다(f.<key>, state, sort·dir, q, cursor) · 칩 다시 누르면 풀림", async () => {
  LIST = url => (url.includes("cursor=50") ? page({ rows: [row("c9", "다음 쪽 글", {})], next_cursor: null }) : page({ next_cursor: "50" }));
  const el = await showMe("#_me/obj/collected_posts", S());
  const chip = (label: string) => [...el.querySelectorAll<HTMLButtonElement>("#obj-list button.chip, #obj-list button")].find(b => b.textContent!.startsWith(label))!;
  await click(chip("Reddit"));
  expect(lists().at(-1)).toBe("/api/me/objects/collected_posts?f.channel=reddit");
  expect(chip("Reddit").getAttribute("aria-pressed")).toBe("true");
  await click(chip("보관"));
  expect(lists().at(-1)).toBe("/api/me/objects/collected_posts?state=kept&f.channel=reddit");
  await click(chip("Reddit"));
  expect(lists().at(-1)).toBe("/api/me/objects/collected_posts?state=kept");
  await click([...el.querySelectorAll<HTMLButtonElement>("#obj-list th button")].find(b => b.textContent === "제목")!);
  expect(lists().at(-1)).toBe("/api/me/objects/collected_posts?sort=title&dir=asc&state=kept");
  await click([...el.querySelectorAll<HTMLButtonElement>("#obj-list th button")].find(b => b.textContent!.startsWith("게시일"))!);
  expect(lists().at(-1)).toBe("/api/me/objects/collected_posts?sort=posted_on&dir=asc&state=kept");   // 지금 정렬 열 = 방향만 뒤집는다
  await type(el.querySelector<HTMLInputElement>("#obj-list input[type=search]")!, "합성 %");
  await act(async () => { await new Promise(r => setTimeout(r, 300)); });
  await flush();
  expect(lists().at(-1)).toBe("/api/me/objects/collected_posts?sort=posted_on&dir=asc&q=%ED%95%A9%EC%84%B1+%25&state=kept");
  await click([...el.querySelectorAll("button")].find(b => b.textContent === "더 보기"));
  expect(lists().at(-1)).toContain("cursor=50");
  expect(text(el, "#obj-list tbody td a")).toContain("다음 쪽 글");
  expect(calls.filter(c => c.method !== "GET")).toEqual([]);
});

test("항목 페이지 — 필드 전부 · AI 필드는 「AI 요약」 표시 · 목록으로 링크 · 없는 오브젝트 key = 안내", async () => {
  const el = await showMe("#_me/obj/collected_posts/c1", S());
  expect(el.querySelector("#home-detail")!.textContent).toContain("합성 글 하나");
  expect(text(el, "#home-detail dl.kv dt")).toEqual(["채널", "작성자", "게시일", "AI 요약문 AI 요약"]);   // 이 항목엔 원 URL 값이 없다
  expect(el.querySelector("#home-detail dl.kv dt .chip.o-ai")!.textContent).toBe("AI 요약");
  expect(el.querySelector("#home-detail .hback a")!.getAttribute("href")).toBe("#_me/obj/collected_posts");
  expect(lists()).toEqual([]);   // 항목 페이지는 상태 S 의 항목 그대로(목록 API 를 부르지 않는다)
  const gone = await showMe("#_me/obj/none_such", S());
  expect(gone.textContent).toContain("이 오브젝트 탭은 없어요");
});

test("옛 주소 — #_me/custom/<id> = 그 항목의 오브젝트 탭 · #_me/custom = 첫 오브젝트 탭 · #_me/item/<id> 도 오브젝트 탭으로", async () => {
  await showMe("#_me/custom/v1", S());
  expect(location.hash).toBe("#_me/obj/verified_results/v1");
  await showMe("#_me/custom", S());
  expect(location.hash).toBe("#_me/obj/collected_posts");
  await showMe("#_me/item/c2", S());
  expect(location.hash).toBe("#_me/obj/collected_posts/c2");
  await showMe("#_me/custom", meState());
  expect(location.hash).toBe("#_me");   // 사용자 오브젝트 없음
});

test("좁은 화면 — 표 대신 카드(제목 + 앞 두 필드)", async () => {
  installMedia(true);
  const el = await showMe("#_me/obj/collected_posts", S());
  expect(el.querySelector("#obj-list table")).toBeNull();
  expect(text(el, "#obj-list li a")).toEqual(["합성 글 하나Reddit, 작성자 갑", "합성 글 둘LinkedIn"]);
});
