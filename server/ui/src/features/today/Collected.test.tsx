// 수집 인박스(2026-11-13 명세 3절) — 등급 묶음 순서·묶음 안 정렬 · 머리 문구 · 「원문 링크 있는 것만」 · 카드(AI 요약 표시·제목 줄 대신) ·
// 펼침(AI 요약 넷 + 원문 본문 없음 안내) · 보관·버림 = 판별 POST(expected_revision) → 목록에서 빠짐 + 되돌리기(직전 상태) ·
// 전부 버림 = 두 번 눌러 확정 · 보관함 = 접힘, 열면 kept 조회, 버튼은 버림만 · 빈 상태(오브젝트 없음·글 없음).
// 2026-11-23 두 칸: 넓은 화면 = 줄을 누르면 오른쪽 읽기 판(고른 줄 aria-current), 판별 뒤 같은 묶음 다음 글, 다시 받아도 유지.
// 한 칸(900 이하) = 읽기 판 없이 줄 아래 펼침.
import { act } from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { queryClient } from "../../shared/queries";
import { calls, click, flush, installFetch, json, serve, text } from "../../test/fakeServer";
import { installMedia } from "../../test/meFixture";
import { byText, hideScreen, showScreen } from "../../test/showScreen";
import { NO_BODY } from "./collectedRows";

type P = Record<string, unknown>;
const post = (id: string, grade: string | null, on: string, extra: P = {}): P => ({
  id, revision: 3, title: `${id} 제목 줄`, channel: "linkedin", author_display: `${id} 작성자`, post_url: `https://x.example/${id}`, posted_on: "2026-11-10",
  collected_on: on, axes: [], ai: { grade, summary: null, as_is: null, to_be: null, ops: null, points: null }, state: "pending", decided_by: null, decided_at: null, ...extra });
let PEND: P[] = [], KEPT: P[] = [], READY = true;
const S = { user: { nav: "new" }, switches: {}, activity_ui: { actions: {}, providers: {}, pending_days: 30 }, inbox: { pending: 0 }, journal: [] };
const show = () => showScreen("today", "#_today", ["today", "", ""], S);
const posts = () => calls.filter(c => c.method === "POST");
const cards = (el: Element) => text(el, "#collected > section li b");
const row = (el: Element, id: string) => el.querySelector(`#collected li[data-id="${id}"]`)!;
const face = (el: Element, id: string) => row(el, id).querySelector("button[data-face]");
const reader = (el: Element) => el.querySelector("#collected-reader")!;
const current = (el: Element) => [...el.querySelectorAll('#collected button[aria-current="true"]')].map(b => b.closest("li")!.getAttribute("data-id"));
// 한 칸(900 이하) — 시험 도우미 installMedia 는 767 질의만 맞추므로 여기서 900 질의를 직접 맞춘다
const oneCol = () => vi.stubGlobal("matchMedia", (q: string) => ({ matches: q.includes("900"), media: q, addEventListener() {}, removeEventListener() {} }));

beforeEach(() => {
  installFetch(); installMedia(false); queryClient.clear();
  READY = true;
  PEND = [post("n1", "news", "2026-11-11"), post("s2", "signal", "2026-11-12"), post("s1", "signal", "2026-11-12"),
    post("z1", "noise", "2026-11-09"), post("u1", null, "2026-11-12", { post_url: null, ai: { grade: null, summary: "AI가 쓴 한 줄", as_is: "지금 꼴", to_be: "다음 꼴", ops: "운영 메모", points: ["요점 하나", "요점 둘"] } }),
    post("n2", "news", "2026-11-12")];
  KEPT = [post("k1", "signal", "2026-11-01", { state: "kept" })];
  serve((url, m) => {
    if (m === "POST" && url.endsWith("/decide")) { PEND = PEND.filter(p => p.id !== url.split("/")[3]); return json(200, { item_id: url.split("/")[3], state: "kept", revision: 4, decided_at: null }); }
    if (m === "POST" && url === "/api/collected/drop") return json(200, { dropped: ["n2", "n1"], skipped: [] });
    if (url === "/api/collected?state=pending") return json(200, { ready: READY, posts: PEND, counts: { pending: PEND.length, kept: KEPT.length } });
    if (url === "/api/collected?state=kept") return json(200, { ready: READY, posts: KEPT, counts: { pending: PEND.length, kept: KEPT.length } });
    if (url === "/api/inbox?state=pending") return json(200, { entries: [], next_cursor: "", counts: { pending: 0 } });
    if (url === "/api/activities?limit=50") return json(200, { activities: [], next_cursor: "" });
    return json(404, {});
  });
});
afterEach(() => hideScreen());

test("묶음 순서(신호, 소식, 노이즈, 등급 없음) · 묶음 안 collected_on 내림차순, id · 머리 · 오늘 탭 맨 위 · 아래 「들어온 내 글과 활동」", async () => {
  const el = await show();
  expect(el.querySelector("#collected")!.compareDocumentPosition(el.querySelector("#home-list")!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(el.querySelector("#today-h")!.textContent).toBe("들어온 내 글과 활동");
  expect(text(el, "#collected h4")).toEqual(["신호", "소식", "노이즈", "등급 없음"]);
  expect(cards(el)).toEqual(["s1 작성자", "s2 작성자", "n2 작성자", "n1 작성자", "z1 작성자", "u1 작성자"]);
  expect(el.querySelector("#collected")!.textContent).toContain("수집 6건 (신호 2), 등급 없음 1");
  expect(byText(el, "#collected button", "전부 버림")).toHaveLength(2);   // 소식, 노이즈만
  const u1 = el.querySelector('li[data-id="u1"]')!;
  expect(u1.querySelector(".chip.o-ai")!.textContent).toBe("AI 요약");
  expect(u1.textContent).toContain("AI가 쓴 한 줄");
  expect(u1.textContent).not.toContain("원문 링크");
  const s1 = el.querySelector('li[data-id="s1"]')!;
  expect(s1.textContent).toContain("s1 제목 줄");
  const a = s1.querySelector("a.link") as HTMLAnchorElement;
  expect([a.textContent, a.getAttribute("href"), a.target, a.rel]).toEqual(["원문 링크", "https://x.example/s1", "_blank", "noopener noreferrer"]);
  await click(el.querySelector("#collected input[type=checkbox]"));
  expect(cards(el)).not.toContain("u1 작성자");
  expect(el.querySelector("#collected")!.textContent).toContain("수집 5건 (신호 2), 등급 없음 0");
  expect(posts()).toEqual([]);
});

test("펼침 — 제목 줄 · AI 요약 넷(as-is, to-be, 운영, 요점) + 「AI 요약」 표시 · 원문 본문 없음 안내", async () => {
  // 한 칸(900 이하)에서 줄 아래로 펼친다, 읽기 판은 없다
  oneCol();
  const el = await show();
  expect(el.querySelector("#collected-reader")).toBeNull();
  const u1 = el.querySelector('li[data-id="u1"]')!;
  await click(u1.querySelector("button[aria-expanded]"));
  expect(u1.querySelector("button[aria-expanded]")!.getAttribute("aria-expanded")).toBe("true");
  expect(text(u1, "dt")).toEqual(["as-is", "to-be", "운영"]);
  expect(text(u1, "dd")).toEqual(["지금 꼴", "다음 꼴", "운영 메모"]);
  expect(text(u1, "ul li")).toEqual(["요점 하나", "요점 둘"]);
  expect(u1.textContent).toContain("u1 제목 줄");
  expect(u1.textContent).toContain(NO_BODY);
  expect(u1.querySelector("button[aria-expanded]")!.getAttribute("aria-controls")).toBe(u1.querySelector("[id^=collected-detail-]")!.id);
  await click(u1.querySelector("button[aria-expanded]"));
  expect(u1.querySelector("dl")).toBeNull();
  expect(posts()).toEqual([]);
});

test("보관 = 판별 POST(expected_revision) → 목록에서 빠짐 + 되돌리기 = 직전 상태(pending)로 판별", async () => {
  const el = await show();
  await click(el.querySelector('li[data-id="s1"]')!.querySelector("button.secondary"));
  expect(posts().map(c => [c.url, c.body])).toEqual([["/api/collected/s1/decide", { state: "kept", expected_revision: 3 }]]);
  expect(el.querySelector('li[data-id="s1"]')).toBeNull();
  expect(el.querySelector("#collected .fok")!.textContent).toContain("보관했어요.");
  await click(byText(el, "#collected button", "되돌리기")[0]);
  expect(posts().at(-1)).toEqual({ url: "/api/collected/s1/decide", method: "POST", body: { state: "pending", expected_revision: 4 } });
  expect(el.querySelector("#collected .fok")!.textContent).toBe("되돌렸어요.");
  await click(byText(el, "li[data-id=\"z1\"] button", "버림")[0]);
  expect(posts().at(-1)!.body).toEqual({ state: "dropped", expected_revision: 3 });
});

test("전부 버림 — 첫 번째는 확인 문구만, 두 번째에 그 묶음 id 로 POST", async () => {
  const el = await show();
  await click(byText(el, "#collected button", "전부 버림")[0]);
  expect(posts()).toEqual([]);
  await click(byText(el, "#collected button", "한 번 더 누르면 2건 버려요")[0]);
  expect(posts().map(c => [c.url, c.body])).toEqual([["/api/collected/drop", { ids: ["n2", "n1"], state: "dropped" }]]);
  expect(el.querySelector("#collected .fok")!.textContent).toBe("2건 버렸어요.");
});

test("보관함 — 접힘(건수만), 열면 kept 조회, 카드 버튼은 버림만", async () => {
  const el = await show();
  const d = el.querySelector("#collected details") as HTMLDetailsElement;
  expect(d.querySelector("summary")!.textContent).toBe("보관함 1건");
  expect(calls.some(c => c.url === "/api/collected?state=kept")).toBe(false);
  await act(async () => { d.open = true; d.dispatchEvent(new Event("toggle")); });
  await flush();
  await flush();
  expect(calls.some(c => c.url === "/api/collected?state=kept")).toBe(true);
  const k1 = d.querySelector('li[data-id="k1"]')!;
  expect(text(k1, "button:not([data-face])")).toEqual(["버림"]);
});

test("빈 상태 — 수집 글 없음 · 담을 자료 종류 없음(보관함 숨김)", async () => {
  PEND = [];
  let el = await show();
  expect(el.querySelector("#collected")!.textContent).toContain("새로 들어온 수집 글이 없어요.");
  expect(el.querySelector("#collected")!.textContent).toContain("수집 0건 (신호 0), 등급 없음 0");
  hideScreen(); queryClient.clear(); READY = false;
  el = await show();
  expect(el.querySelector("#collected")!.textContent).toContain("key collected_posts");
  expect(el.querySelector("#collected details")).toBeNull();
});

test("두 칸 — 읽기 판 빈 상태, 줄(진짜 button, Enter, Space) 누르면 읽기 판에 그 글 + 고른 줄 aria-current, 다른 줄로 바뀜, 쓰기 없음", async () => {
  const el = await show();
  expect(reader(el).textContent).toBe("왼쪽에서 글을 누르면 여기에 요약이 보여요.");
  expect(el.querySelector("#collected #collected-reader")).toBeNull();   // 읽기 판은 인박스 밖 오른쪽 칸
  const f = face(el, "s1") as HTMLButtonElement;
  expect([f.tagName, f.type, f.getAttribute("aria-controls"), f.hasAttribute("aria-expanded")]).toEqual(["BUTTON", "button", "collected-reader", false]);
  expect(f.querySelector("button")).toBeNull();   // 버튼 안에 버튼 없음
  await click(f);
  expect(current(el)).toEqual(["s1"]);
  const r = reader(el);
  expect(r.querySelector("b")!.textContent).toBe("s1 작성자");
  expect(r.textContent).toContain("LinkedIn");
  expect(r.textContent).toContain("11월 10일 게시");
  expect(r.textContent).toContain("s1 제목 줄");
  expect(r.textContent).toContain(NO_BODY);
  expect(text(r, "button")).toEqual(["보관", "버림"]);
  expect((r.querySelector("a.link") as HTMLAnchorElement).getAttribute("href")).toBe("https://x.example/s1");
  expect(row(el, "s1").querySelector("dl")).toBeNull();   // 두 칸에서는 줄 아래로 펼치지 않는다
  await click(face(el, "u1"));
  expect(current(el)).toEqual(["u1"]);
  expect(text(reader(el), "dt")).toEqual(["as-is", "to-be", "운영"]);
  expect(text(reader(el), "dd")).toEqual(["지금 꼴", "다음 꼴", "운영 메모"]);
  expect(text(reader(el), "ul li")).toEqual(["요점 하나", "요점 둘"]);
  expect(reader(el).querySelector(".chip.o-ai")!.textContent).toBe("AI 요약");
  expect(reader(el).querySelector("a.link")).toBeNull();
  expect(posts()).toEqual([]);
});

test("읽기 판 판별 = 같은 묶음 다음 글, 마지막이면 빈 상태, 고르지 않은 줄 버튼은 읽기 판을 안 바꿈, 다시 받아도 고른 글 유지", async () => {
  const el = await show();
  await click(face(el, "s1"));
  await click(byText(row(el, "n2"), "button", "보관")[0]);
  expect(posts().map(c => c.url)).toEqual(["/api/collected/n2/decide"]);
  expect(current(el)).toEqual(["s1"]);
  expect(reader(el).querySelector("b")!.textContent).toBe("s1 작성자");
  await click(byText(reader(el), "button", "보관")[0]);
  expect(posts().at(-1)).toEqual({ url: "/api/collected/s1/decide", method: "POST", body: { state: "kept", expected_revision: 3 } });
  expect(row(el, "s1")).toBeNull();
  expect(current(el)).toEqual(["s2"]);
  expect(reader(el).querySelector("b")!.textContent).toBe("s2 작성자");
  expect(byText(el, "#collected button", "되돌리기")).toHaveLength(1);   // 되돌리기 5초 그대로
  await click(byText(reader(el), "button", "버림")[0]);
  expect(posts().at(-1)!.body).toEqual({ state: "dropped", expected_revision: 3 });
  expect(reader(el).textContent).toBe("왼쪽에서 글을 누르면 여기에 요약이 보여요.");   // 신호 묶음의 마지막 글이었다
  expect(document.activeElement).toBe(reader(el));
  await click(face(el, "n1"));
  await act(async () => { await queryClient.invalidateQueries({ queryKey: ["collected"] }); });
  await flush();
  expect(current(el)).toEqual(["n1"]);
  expect(reader(el).querySelector("b")!.textContent).toBe("n1 작성자");
});

test("보관함 글 고르기 = 읽기 판에 버림만, 수집 글을 담을 자료 종류가 없으면 읽기 판 칸도 없음", async () => {
  const el = await show();
  const d = el.querySelector("#collected details") as HTMLDetailsElement;
  await act(async () => { d.open = true; d.dispatchEvent(new Event("toggle")); });
  await flush();
  await flush();
  await click(face(el, "k1"));
  expect(current(el)).toEqual(["k1"]);
  expect(text(reader(el), "button")).toEqual(["버림"]);
  hideScreen(); queryClient.clear(); READY = false;
  const e2 = await show();
  expect(e2.querySelector("#collected-reader")).toBeNull();
});
