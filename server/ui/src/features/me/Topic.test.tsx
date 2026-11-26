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
const base = meState();
const S = () => meState({
  definitions: [...base.definitions, def("od_tp", "topics", "주제"), def("od_pl", "plain_notes", "그냥 메모")],
  items: [...base.items, it("i_tp", "od_tp", "가짜 주제"), it("i_pl", "od_pl", "손으로 쓴 메모")],
});
let FAIL = false;

beforeEach(() => {
  installFetch(); installMedia(false); queryClient.clear(); FAIL = false;
  serve(url => url === "/api/me/layout" ? json(200, layout()) : url === "/api/me/stats" ? json(200, STATS) : url.startsWith("/api/journal") ? json(200, JOURNAL)
    : url.startsWith("/api/item?") ? (FAIL ? json(500, { code: "X", msg: "x" }) : json(200, { id: "i_tp", thread: THREAD }))
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
