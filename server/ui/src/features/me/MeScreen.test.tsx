// 「나」 보기(옛 test_web_home.py test_static 「나」 절을 실행 시험으로) — 요약 = 레이아웃 순서 블록(레지스트리) · 기본 배치 · 통계 실패 ·
// 하위 탭 순서 · 진입 = 연결 최다 replace · 항목 상세·연결 그래프(저장된 관계만) · 옛 주소 replace · 내 글 본문 · 1열 · 쓰기 요청 0(보기만).
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { queryClient } from "../../shared/queries";
import { calls, installFetch, json, serve, text } from "../../test/fakeServer";
import { installMedia, JOURNAL, layout, meState, STATS, TABS } from "../../test/meFixture";
import { hideMe, showMe } from "../../test/showMe";
import { REGISTRY } from "../../layout/meEntry";

let LAYOUT: unknown = layout(), STATS_R: unknown = STATS;
beforeEach(() => {
  installFetch();
  installMedia(false);
  queryClient.clear();
  LAYOUT = layout(); STATS_R = STATS;
  serve(url => {
    if (url === "/api/me/layout") return LAYOUT ? json(200, LAYOUT) : json(500, {});
    if (url === "/api/me/stats") return STATS_R ? json(200, STATS_R) : json(500, {});
    if (url.startsWith("/api/journal?id=r1")) return json(200, JOURNAL);
    if (url.startsWith("/api/axes/")) return json(200, { activities: [], activity_count: 0 });
    return json(404, { code: "NOT-FOUND", msg: "" });
  });
});
afterEach(() => { hideMe(); vi.unstubAllGlobals(); });
const posts = () => calls.filter(c => c.method !== "GET");

test("요약 = 레이아웃 regions.summary 순서 · 레지스트리 밖 블록은 건너뜀 · 숫자는 서버 통계 그대로 · 버튼 0", async () => {
  LAYOUT = layout(["decision", ...TABS.filter(t => t !== "decision")], ["recent", "kinds", "nope", "heatmap"]);
  const el = await showMe("#_me/summary", meState());
  expect(text(el, "#me-summary h3")).toEqual(["최근 변경", "종류별 건수", "13주 글·활동"]);
  expect(text(el, "nav a").map(t => t!.replace(/\d/g, ""))).toEqual(["결정", "요약", "기준", "축", "커스텀", "사람", "출처"]);
  expect(el.querySelector("#me-summary")!.textContent).toContain("기준 2");
  expect(el.querySelectorAll("nav a svg[role=img][aria-label=표준]").length).toBe(5);   // 자물쇠 = 접근성 이름 「표준」(결정·기준·축·사람·출처)
  expect(el.querySelectorAll("#me-summary svg[aria-label=표준]").length).toBe(5);
  expect(el.querySelectorAll("#me-summary button").length).toBe(0);
  expect(el.querySelector("svg[aria-label^='13주']")!.getAttribute("aria-label")).toContain("합 2");
  expect(posts()).toEqual([]);
});

test("레이아웃 못 받음 = 기본 배치(server/layout_registry.json default) · 통계 못 받음 = 새로 고침 안내", async () => {
  LAYOUT = null; STATS_R = null;
  const el = await showMe("#_me/summary", meState());
  const def = REGISTRY.pages.me.default;
  expect(text(el, "#me-summary h3")).toEqual(["13주 글·활동", "종류별 건수", "기다리는 결정", "최근 변경"]);
  expect(def.regions.summary.map(s => s.c)).toEqual(["heatmap", "kinds", "waiting", "recent"]);
  expect(el.textContent).toContain("통계를 불러오지 못했어요. 새로 고침해 주세요.");
  expect(text(el, "nav a").length).toBe(def.tabs.length);
});

test("기준 탭 진입(넓은 화면) = 연결 최다 항목으로 주소 replace · 옛 #_me/item/<id> = 그 항목의 탭 · 모르는 탭 = 첫 탭", async () => {
  await showMe("#_me/principle", meState());
  expect(location.hash).toBe("#_me/principle/p1");
  await showMe("#_me/item/a2", meState());
  expect(location.hash).toBe("#_me/axis/a2");
  await showMe("#_me/zzz", meState());
  expect(location.hash).toBe("#_me/summary");
  await showMe("#_me/s1", meState());   // 옛 「나」 홈 출처 고르기 링크
  expect(location.hash).toBe("#_obj/source/s1");
});

test("항목 상세 — 코드·제목·본문 굵게(요소는 strong 만)·렌즈 칩 · 연결 = 저장된 관계(근거 판단) · 옆 묶음", async () => {
  const el = await showMe("#_me/principle/p1", meState());
  const d = el.querySelector("#home-detail")!;
  expect(d.querySelector("h2")!.textContent).toBe("P-1 담당이 먼저");
  expect(text(d, "strong")).toContain("굵게");
  expect(d.textContent).toContain("근거 역추적");
  expect(d.querySelector("svg[aria-label$='연결 그래프']")!.getAttribute("aria-label")).toBe("P-1 담당이 먼저의 연결 그래프");
  // 고칠 수 있는 값 = 늘 보이는 연필(접근성 이름 「고치기」) — 제목·본문
  expect([...d.querySelectorAll("button[title='눌러서 고치기'] svg[role=img]")].map(s => s.getAttribute("aria-label"))).toEqual(["고치기", "고치기"]);
  expect([...d.querySelectorAll("svg[aria-label$='연결 그래프'] a")].map(a => a.getAttribute("href"))).toEqual(["#_me/cand/c1"]);
  expect(el.querySelector("aside")!.textContent).toContain("담당 먼저");
  expect(text(el, "#home-list li a .ht")).toEqual(["P-1 담당이 먼저", "두 번째 기준"]);
  expect(posts()).toEqual([]);
});

test("축 띠 = 축 항목 코드 순 색 · 서버 건수 · 칩 링크", async () => {
  const el = await showMe("#_me/axis/a1", meState());
  const chips = [...el.querySelectorAll("section[aria-label='축별 연결 건수'] a")];
  expect(chips.map(a => a.getAttribute("href"))).toEqual(["#_me/axis/a1", "#_me/axis/a2"]);
  expect(chips[0].getAttribute("aria-current")).toBe("true");
  expect((chips[0].querySelector("i") as HTMLElement).style.background).toBe("var(--ax1)");
  expect(chips.map(a => a.textContent)).toEqual(["고객 이해1", "실행 속도0"]);
});

test("내 글 상세(옛 #_me/journal/<id>) — 본문은 /api/journal · 제목 문단은 빼고 굵게만 · 연결(질문·출처·축·판단)", async () => {
  const el = await showMe("#_me/journal/r1", meState());
  expect(calls.some(c => c.url === "/api/journal?id=r1")).toBe(true);
  const d = el.querySelector("#home-detail")!;
  expect(text(d, ".doc p")).toEqual(["도입 회의에서 입력 담당을 먼저 정했다.", "둘째 문단"]);
  expect(text(d, ".doc strong")).toEqual(["담당"]);
  expect([...d.querySelectorAll("svg a")].map(a => a.getAttribute("href")).sort()).toEqual(["#_me/cand/c1", "#_me/item/a1", "#_me/q/q1", "#_obj/source/s1"]);
  expect(d.querySelector("svg title")).toBeTruthy();
  expect(el.textContent).not.toContain("축별 연결 건수");
});

test("없는 데이터 = 열 수 없음 + 목록 링크 · 연결 목록 보기 = 이름·종류·관계·방향", async () => {
  let el = await showMe("#_me/cand/nope", meState());
  expect(el.querySelector("#home-detail")!.textContent).toContain("이 데이터를 열 수 없어요.");
  el = await showMe("#_me/cand/c1", meState());
  const { click } = await import("../../test/fakeServer");
  await click([...el.querySelectorAll("button")].find(b => b.textContent === "목록으로 보기"));
  expect(text(el, "#home-detail li .hk")).toEqual(["내 글 · 근거 · 이 데이터가 가리킴", "질문 · 질문 · 이 데이터가 가리킴", "기준 · claims · 이 데이터를 가리킴"]);
});

test("1열(좁은 폭) 첫 진입 = 목록만(주소 그대로) · 상세 = [목록] 버튼", async () => {
  installMedia(true);
  let el = await showMe("#_me/principle", meState());
  expect(location.hash).toBe("#_me/principle");
  expect(el.querySelector("#home-detail")).toBeNull();
  el = await showMe("#_me/principle/p2", meState());
  expect(el.querySelector("#home-list")).toBeNull();
  expect(text(el, ".hback button")).toEqual(["목록"]);
});
