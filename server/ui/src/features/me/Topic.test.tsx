// 주제 잇기 화면(2026-11-26) — 주제 오브젝트(key topics) 항목 페이지에 붙은 글 한 줄기(날짜, 제목 링크, 본문 = 글자 그대로)를
// GET /api/item 의 thread 순서대로. 다른 오브젝트 항목은 부르지 않는다. 자료는 가짜 문장.
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { queryClient } from "../../shared/queries";
import { calls, installFetch, json, serve } from "../../test/fakeServer";
import { installMedia, JOURNAL, layout, meState, STATS } from "../../test/meFixture";
import { hideMe, showMe } from "../../test/showMe";

const XSS = '<img src=x onerror="alert(1)"><script>alert(2)</script>';
const def = (id: string, key: string, label: string) => ({ id, key, label, std_id: null, archived_at: null, semantic_kind: "collection", fields: [] });
const it = (id: string, object_id: string, title: string) => ({ id, object_id, code: null, title, body: "", data: {}, decision: null, revision: 1,
  semantic_kind: "collection", proposal: null, links: [], created_at: "2026-11-01T01:00:00+00:00", updated_at: "2026-11-01T01:00:00+00:00" });
const THREAD = [
  { record_id: "r_t1", title: "가짜 첫째 날", body: "첫째 날 문단.\n둘째 줄.", on: "2026-11-18" },
  { record_id: "r_t2", title: "가짜 둘째 날", body: XSS, on: "2026-11-19" },
  { record_id: "r_t3", title: null, body: "셋째 날 문단.", on: "2026-11-20" },
];
// 하위 목록(2026-11-27) — 서버 순서(오브젝트 → 날짜) 그대로 오브젝트별 절. 요약 칸은 서버가 고른 것 그대로
const CHILDREN = [
  { item_id: "i_s1", title: "가짜 이야기 하나", on: "2026-11-18", object_id: "od_st", object_label: "세션 스토리",
    summary: [{ key: "scene", label: "장면", text: "가짜 장면 문장." }, { key: "why", label: "이유", text: XSS }] },
  { item_id: "i_s2", title: "가짜 이야기 둘", on: "2026-11-19", object_id: "od_st", object_label: "세션 스토리", summary: [] },
  { item_id: "i_d1", title: "가짜 결정 하나", on: "2026-11-18", object_id: "od_dc", object_label: "소통과 결정",
    summary: [{ key: "said", label: "말", text: "가짜 말 문장." }] },
];
let KIDS: unknown[] = [];
const base = meState();
const S = () => meState({
  definitions: [...base.definitions, def("od_tp", "topics", "주제"), def("od_pl", "plain_notes", "그냥 메모"),
    def("od_st", "fake_story", "세션 스토리"), def("od_dc", "fake_decide", "소통과 결정")],
  items: [...base.items, it("i_tp", "od_tp", "가짜 주제"), it("i_pl", "od_pl", "손으로 쓴 메모")],
});
let FAIL = false;

beforeEach(() => {
  installFetch(); installMedia(false); queryClient.clear(); FAIL = false; KIDS = [];
  serve(url => url === "/api/me/layout" ? json(200, layout()) : url === "/api/me/stats" ? json(200, STATS) : url.startsWith("/api/journal") ? json(200, JOURNAL)
    : url.startsWith("/api/item?") ? (FAIL ? json(500, { code: "X", msg: "x" }) : json(200, { id: "i_tp", thread: THREAD, children: KIDS }))
    : json(200, { activities: [], activity_count: 0 }));
});
afterEach(() => { hideMe(); vi.unstubAllGlobals(); });

test("주제 항목 — 붙은 글을 날짜순 한 줄기로(날짜, 제목 링크, 본문 글자 그대로), 편 수", async () => {
  const el = await showMe("#_me/obj/topics/i_tp", S());
  expect(calls.some(c => c.url === "/api/item?id=i_tp")).toBe(true);
  const sec = el.querySelector('[aria-labelledby="hthread-h"]')!;
  expect(sec.querySelector("h3")!.textContent).toBe("이 주제의 글");
  expect(sec.querySelector(".hk")!.textContent).toBe("3편");
  const rows = [...sec.querySelectorAll("li")];
  expect(rows.map(r => r.querySelector("a")!.textContent)).toEqual(["가짜 첫째 날", "가짜 둘째 날", "(제목 없음)"]);
  expect(rows.map(r => r.querySelector("a")!.getAttribute("href"))).toEqual(["#_me/journal/r_t1", "#_me/journal/r_t2", "#_me/journal/r_t3"]);
  expect(rows[0].textContent).toContain("11월 18일");
  expect(rows[0].textContent).toContain("첫째 날 문단.");
  expect(rows[1].textContent).toContain(XSS);   // 본문의 태그는 요소가 되지 않는다
  expect(el.querySelector("#home-detail img, #home-detail script")).toBeNull();
});

test("다른 오브젝트 항목 — 글 한 줄기 없음, /api/item 부르지 않음", async () => {
  const el = await showMe("#_me/obj/plain_notes/i_pl", S());
  expect(el.querySelector('[aria-labelledby="hthread-h"]')).toBeNull();
  expect(calls.some(c => c.url.startsWith("/api/item?"))).toBe(false);
});

test("불러오기 실패 — 문구와 [다시 시도]", async () => {
  FAIL = true;
  const el = await showMe("#_me/obj/topics/i_tp", S());
  const sec = el.querySelector('[aria-labelledby="hthread-h"]')!;
  expect(sec.textContent).toContain("글을 불러오지 못했어요.");
  expect(sec.querySelector("button")!.textContent).toBe("다시 시도");
});

test("하위 목록 — 오브젝트별 절(이름 = 오브젝트 이름, 줄 수), 날짜, 제목 = 그 항목 페이지, 요약 칸 글자 그대로", async () => {
  KIDS = CHILDREN;
  const el = await showMe("#_me/obj/topics/i_tp", S());
  const st = el.querySelector('[aria-labelledby="hchild-od_st"]')!, dc = el.querySelector('[aria-labelledby="hchild-od_dc"]')!;
  expect(st.querySelector("h3")!.textContent).toBe("세션 스토리");
  expect(st.querySelector(".hk")!.textContent).toBe("2");
  expect([...st.querySelectorAll("li a")].map(a => [a.textContent, a.getAttribute("href")])).toEqual(
    [["가짜 이야기 하나", "#_me/obj/fake_story/i_s1"], ["가짜 이야기 둘", "#_me/obj/fake_story/i_s2"]]);
  const first = st.querySelector("li")!;
  expect(first.textContent).toContain("11월 18일");
  expect(first.textContent).toContain("장면 가짜 장면 문장.");
  expect(first.textContent).toContain(XSS);   // 요약 칸의 태그는 요소가 되지 않는다
  expect(el.querySelector("#home-detail img, #home-detail script")).toBeNull();
  expect(dc.querySelector("h3")!.textContent).toBe("소통과 결정");
  expect(dc.textContent).toContain("말 가짜 말 문장.");
  // 절 순서 = 서버 순서, 「이 주제의 글」 다음
  const order = [...el.querySelectorAll("#home-detail section h3")].map(h => h.textContent);
  expect(order.indexOf("이 주제의 글")).toBeLessThan(order.indexOf("세션 스토리"));
  expect(order.indexOf("세션 스토리")).toBeLessThan(order.indexOf("소통과 결정"));
});

test("하위 목록 없음 — 절을 그리지 않는다", async () => {
  const el = await showMe("#_me/obj/topics/i_tp", S());
  expect(el.querySelectorAll('[aria-labelledby="hthread-h"] li').length).toBe(3);   // 응답은 받았다
  expect(el.querySelector('[aria-labelledby^="hchild-"]')).toBeNull();
});

test("이 주제의 글 = 머리 문단만 — 첫 소제목(###) 앞까지 · 소제목 없으면 전체 · 머리 문단이 비면 제목 줄만", async () => {
  const T3 = [
    { record_id: "r_h1", title: "가짜 소제목 있음", body: "머리 문단 첫 줄.\n머리 둘째 줄.\n### S-1. 가짜 소제목\n- 장면: 아래 절에 나오는 줄.", on: "2026-11-18" },
    { record_id: "r_h2", title: "가짜 소제목 없음", body: "소제목 없는 본문 전체.\n둘째 줄.", on: "2026-11-19" },
    { record_id: "r_h3", title: "가짜 머리 빔", body: "\n### D-1. 가짜 결정\n- 말: 아래 절에 나오는 말.", on: "2026-11-20" },
  ];
  serve(url => url === "/api/me/layout" ? json(200, layout()) : url === "/api/me/stats" ? json(200, STATS) : url.startsWith("/api/journal") ? json(200, JOURNAL)
    : url.startsWith("/api/item?") ? json(200, { id: "i_tp", thread: T3, children: [] }) : json(200, { activities: [], activity_count: 0 }));
  const el = await showMe("#_me/obj/topics/i_tp", S());
  const rows = [...el.querySelectorAll('[aria-labelledby="hthread-h"] li')];
  expect(rows[0].textContent).toContain("머리 문단 첫 줄.\n머리 둘째 줄.");
  expect(rows[0].textContent).not.toContain("S-1.");
  expect(rows[0].textContent).not.toContain("장면");
  expect(rows[1].textContent).toContain("소제목 없는 본문 전체.\n둘째 줄.");
  expect(rows[2].querySelector("a")!.textContent).toBe("가짜 머리 빔");
  expect(rows[2].children.length).toBe(1);   // 제목 줄만(본문 칸 없음)
  expect(rows[2].textContent).not.toContain("D-1.");
});
