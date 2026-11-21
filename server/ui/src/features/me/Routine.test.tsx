// 루틴판 블록(2026-11-21 명세 4절) — 세 열 큰 숫자·뜻 · 줄 3개(MM-DD 앞, 대상 링크) · 외 N건 · 쓰는 중 카드 = 한판 상세 링크 · since 줄 숨김 규칙
// · 설정 없음/오브젝트 없음 = 안내 한 줄 · 오브젝트 탭 항목 페이지 「한판으로 보기」(한판 오브젝트에만) · 버튼 0. 문장은 모두 가짜다.
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { queryClient } from "../../shared/queries";
import { mmdd } from "../../shared/date";
import { installFetch, json, serve, text } from "../../test/fakeServer";
import { installMedia, JOURNAL, meState, STATS, TABS } from "../../test/meFixture";
import { hideMe, showMe } from "../../test/showMe";
import sample from "./routine.sample.json";

const P = { in: "collected_posts", decided: "pivots", writing: "publications", lines: "front_lines", subheads: "subheads" };
const lay = (p: object = P) => ({ layout: { v: 2, pages: { me: { tabs: TABS, regions: { summary: [{ c: "routine", p }, { c: "heatmap", p: {} }] } } } }, version: 3 });
const line = (date: string, text: string, target: object) => ({ date, text, target });
const card = (item_id: string, key_line: string, n_posts: number, n_records: number) => ({ item_id, key_line, date: "2026-11-18", n_subheads: 2, n_sources: n_posts + n_records, n_posts, n_records });
const BOARD = () => ({ ...structuredClone(sample.board),
  in: { ...sample.board.in, lines: [line("2026-11-20", "가짜 줄 하나", { kind: "item", id: "c1", object_key: "collected_posts", item_id: "c1" }),
    line("2026-11-19T23:00:00+09:00", "가짜 줄 둘", { kind: "item", id: "c2", object_key: "collected_posts" }), line("2026-11-18", "가짜 줄 셋", { kind: "item", id: "c3", object_key: "collected_posts" })] },
  decided: { ...sample.board.decided, lines: [line("2026-11-17", "가짜 결정 줄", { kind: "record", id: "r9", object_key: "pivots", item_id: "v9" }),
    line("2026-11-16", "기록만 있는 줄", { kind: "record", id: "r8", object_key: "" })], more: 4 },
  writing: { drafts: 2, cards: [card("w1", "가짜 한판 하나", 2, 3), card("w2", "가짜 한판 둘", 0, 1), card("w3", "가짜 한판 셋", 0, 0)] } });
let ROUTINE: () => object = BOARD, LAY: () => object = () => lay();

beforeEach(() => {
  installFetch(); installMedia(false); queryClient.clear(); ROUTINE = BOARD; LAY = () => lay();
  serve(url => (url === "/api/me/layout" ? json(200, LAY()) : url === "/api/me/stats" ? json(200, STATS) : url.startsWith("/api/journal") ? json(200, JOURNAL)
    : url === "/api/me/routine" ? json(200, ROUTINE()) : json(200, { activities: [], activity_count: 0 })));
});
afterEach(() => { hideMe(); vi.unstubAllGlobals(); });

test("MM-DD 헬퍼 — 날짜 글자를 자른다(시간대 이동 없음) · 못 읽으면 빈 칸", () => {
  expect([mmdd("2026-11-20"), mmdd("2026-11-19T23:30:00+09:00"), mmdd(""), mmdd(null), mmdd("11/20")]).toEqual(["11-20", "11-19", "", "", ""]);
});

test("세 열 — 큰 숫자 = n_7d · unknown · drafts, 뜻 한 줄, 판정 없음 · 줄 = MM-DD 앞 + 대상 링크 · 외 N건 · 카드 = 한판 상세", async () => {
  const el = await showMe("#_me/summary", meState());
  const rt = el.querySelector("#routine")!;
  expect(text(rt, "h3")).toEqual(["들어온 것", "내가 정한 것", "쓰는 중"]);
  expect(text(rt, "b")).toEqual(["9", "5", "2"]);
  expect(rt.querySelector("#rt-in")!.textContent).toContain("이번 주 읽은 글, 그중 신호 3");
  expect(rt.querySelector("#rt-decided")!.textContent).toContain("결과를 아직 확인 안 한 결정판정 없음 2");
  expect(rt.querySelector("#rt-writing")!.textContent).toContain("이렇게 해야 한다로 정리 중");
  const links = (sel: string) => [...rt.querySelectorAll(`${sel} li a`)].map(a => [a.textContent, a.getAttribute("href")]);
  expect(links("#rt-in")).toEqual([["11-20가짜 줄 하나", "#_me/obj/collected_posts/c1"], ["11-19가짜 줄 둘", "#_me/obj/collected_posts/c2"], ["11-18가짜 줄 셋", "#_me/obj/collected_posts/c3"]]);
  expect(links("#rt-decided")).toEqual([["11-17가짜 결정 줄", "#_me/obj/pivots/v9"], ["11-16기록만 있는 줄", "#_me/journal/r8"]]);
  expect(rt.querySelector("#rt-in")!.textContent).toContain("외 2건");
  expect(rt.querySelector("#rt-decided")!.textContent).toContain("외 4건");
  expect(links("#rt-writing")).toEqual([["가짜 한판 하나글 2, 결정 3", "#_me/board/w1"], ["가짜 한판 둘결정 1", "#_me/board/w2"], ["가짜 한판 셋출처 없음", "#_me/board/w3"]]);   // 0 인 쪽은 뺀다
  expect(rt.querySelector("#rt-since")!.textContent).toBe("지난 루틴 뒤 들어온 것 4, 정한 것 1. 다듬을 것 10. 대화에서 '루틴 하자'");
  expect(rt.querySelectorAll("button").length).toBe(0);
  expect(el.querySelector("#me-summary")!.firstElementChild!.id).toBe("routine");   // 레이아웃 순서 그대로(맨 앞)
});

test("since 줄 — 셋(들어온 것, 정한 것, 다듬을 것)이 모두 0 이면 숨김, 하나라도 있으면 보임 · 외 N건은 0 이면 없음", async () => {
  const zero = () => { const b = BOARD(); b.since = { new_in: 0, new_decided: 0 }; b.in.unrefined = 0; b.decided.unrefined = 0; b.in.more = 0; return b; };
  ROUTINE = zero;
  let el = await showMe("#_me/summary", meState());
  expect(el.querySelector("#rt-since")).toBeNull();
  expect(el.querySelector("#rt-in")!.textContent).not.toContain("외 ");
  hideMe(); queryClient.clear();
  ROUTINE = () => { const b = zero(); b.decided.unrefined = 1; return b; };
  el = await showMe("#_me/summary", meState());
  expect(el.querySelector("#rt-since")!.textContent).toBe("지난 루틴 뒤 들어온 것 0, 정한 것 0. 다듬을 것 1. 대화에서 '루틴 하자'");
});

test("설정 없음(ready false) · 없는 오브젝트(missing) = 안내 한 줄만(숫자·줄 없음)", async () => {
  for (const r of [{ ready: false }, { ...BOARD(), missing: ["front_lines"] }]) {
    ROUTINE = () => r;
    const el = await showMe("#_me/summary", meState());
    const rt = el.querySelector("#routine")!;
    expect(rt.textContent).toBe("어떤 오브젝트를 열에 둘지 대화로 정하세요");
    expect(rt.querySelectorAll("b, li").length).toBe(0);
    hideMe(); queryClient.clear();
  }
});

test("오브젝트 탭 항목 페이지 — 한판 오브젝트(routine p.writing)에만 「한판으로 보기」 링크 하나", async () => {
  const def = (id: string, key: string, label: string) => ({ id, key, label, std_id: null, archived_at: null, fields: [] });
  const it = (id: string, object_id: string) => ({ id, object_id, code: null, title: "가짜 " + id, body: "", data: {}, decision: null, revision: 1,
    semantic_kind: "collection", proposal: null, links: [], created_at: "2026-11-01T01:00:00+00:00", updated_at: "2026-11-01T01:00:00+00:00" });
  const base = meState();
  const S = meState({ definitions: [...base.definitions, def("od_pub", "publications", "한판"), def("od_pv", "pivots", "피벗")],
    items: [...base.items, it("b1", "od_pub"), it("v1", "od_pv")] });
  let el = await showMe("#_me/obj/publications/b1", S);
  expect(text(el, "#board-link a")).toEqual(["한판으로 보기"]);
  expect(el.querySelector("#board-link a")!.getAttribute("href")).toBe("#_me/board/b1");
  hideMe();
  el = await showMe("#_me/obj/pivots/v1", S);
  expect(el.querySelector("#board-link")).toBeNull();
  hideMe(); queryClient.clear(); LAY = () => lay({});
  el = await showMe("#_me/obj/publications/b1", S);
  expect(el.querySelector("#board-link")).toBeNull();   // 블록 설정이 없으면 링크 없음
});
