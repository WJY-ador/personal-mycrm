// Setup 「페이지 레이아웃」(옛 test_web_home.py S4 정적 절을 옮김) — 레지스트리 이름·자물쇠 · v2 그대로 PUT(version = 마지막 응답) · 한 번에 하나(보내는 중이면
// 마지막 배치만 줄 세움) · 실패 = 마지막 저장 배치로 복원 · STALE = 서버 배치 다시 받기 · 기본으로 되돌리기 = DELETE · 못 읽음 = 기본 배치 + 안내 ·
// 저장 응답 = 「나」와 같은 캐시(QK.layout) · 끌어 놓기(마우스)·Alt + 화살표.
import { act } from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { queryClient } from "../../../shared/queries";
import { calls, click, flush, installFetch, json, serve, text } from "../../../test/fakeServer";
import { hideScreen, showScreen } from "../../../test/showScreen";
import reg from "../../../../../layout_registry.json";
import { QK } from "../useWorld";
import { LAY_TEXT } from "./useLay";

const DEF = reg.pages.me.default;
const lay = (tabs: string[], summary = DEF.regions.summary, version = 3) => ({ layout: { v: 2, pages: { me: { tabs, regions: { summary } } } }, version });
const SWAP = ["principle", "summary", ...DEF.tabs.slice(2)];
let server = lay(SWAP);
let put: (body: { layout: { pages: { me: { tabs: string[] } } }; version: number }) => Response | Promise<Response>;

const show = () => showScreen("layout", "#_setup/layout", [], {});
const lis = (el: Element, i: number) => [...el.querySelectorAll("ol")[i].querySelectorAll("li")];
const keys = (el: Element, i: number) => lis(el, i).map(li => li.dataset.layKey);
const msg = (el: Element) => el.querySelector("#lay-msg")!.textContent;
const resetBtn = (el: Element) => [...el.querySelectorAll("button")].find(b => b.textContent === "기본으로 되돌리기")!;
const writes = () => calls.filter(c => c.method !== "GET");
async function alt(li: Element, key: string) {
  await act(async () => { li.dispatchEvent(new KeyboardEvent("keydown", { key, altKey: true, bubbles: true })); });
  await flush();
}

beforeEach(() => {
  installFetch(); queryClient.clear();
  server = lay(SWAP);
  put = body => json(200, { layout: body.layout, version: body.version + 1 });
  serve(async (_url, m) => {
    const c = calls[calls.length - 1];
    if (m === "PUT") return put(c.body as Parameters<typeof put>[0]);
    if (m === "DELETE") return json(200, lay(DEF.tabs, DEF.regions.summary, 9));
    return json(200, server);
  });
});
afterEach(() => { hideScreen(); vi.unstubAllGlobals(); });

test("서버 배치 그대로 · 탭 이름·자물쇠(기본 종류) · 블록 이름 = 레지스트리 · 기본과 다르면 [기본으로 되돌리기] 켜짐", async () => {
  const el = await show();
  expect(text(el, "h2")).toEqual(["페이지 레이아웃 — 「나」"]);
  expect(keys(el, 0)).toEqual(SWAP);
  expect(lis(el, 0).map(li => li.textContent)).toEqual(["⠿기준 ", "⠿요약", "⠿결정 ", "⠿축 ", "⠿커스텀", "⠿사람 ", "⠿출처 "]);
  expect(lis(el, 0)[0].getAttribute("aria-label")).toBe("기준 — 1번째");
  expect(lis(el, 1).map(li => li.textContent!.slice(1))).toEqual(DEF.regions.summary.map(s => reg.components[s.c as keyof typeof reg.components].label));
  expect(resetBtn(el).disabled).toBe(false);
});

test("기본 배치 = [기본으로 되돌리기] 꺼짐 · 못 읽음 = 기본 배치 + 안내 · 꺼짐", async () => {
  server = lay(DEF.tabs);
  let el = await show();
  expect(resetBtn(el).disabled).toBe(true);
  hideScreen(); queryClient.clear();
  serve(() => json(500, { code: "X" }));
  el = await show();
  expect(keys(el, 0)).toEqual(DEF.tabs);
  expect(msg(el)).toBe(LAY_TEXT.noApi);
  expect(resetBtn(el).disabled).toBe(true);
});

test("Alt + 화살표 = PUT 1(v2 전체 · version = 마지막 응답) · 저장 응답이 「나」 캐시로 · 다음 PUT 은 새 version · 블록 props 그대로", async () => {
  server = lay(DEF.tabs, [{ c: "heatmap", p: { weeks: 13 } }, ...DEF.regions.summary.slice(1)]);
  const el = await show();
  await alt(lis(el, 0)[0], "ArrowRight");
  expect(writes()).toEqual([{ url: "/api/me/layout", method: "PUT", body: { layout: { v: 2, pages: { me: { tabs: SWAP, regions: server.layout.pages.me.regions } } }, version: 3 } }]);
  expect(msg(el)).toBe(LAY_TEXT.saved);
  expect(queryClient.getQueryData<typeof server>(QK.layout)!.layout.pages.me.tabs).toEqual(SWAP);
  await alt(lis(el, 1)[0], "ArrowDown");
  const b = writes()[1].body as typeof server;
  expect(b.version).toBe(4);
  expect(b.layout.pages.me.regions.summary.map(s => s.c)).toEqual(["kinds", "heatmap", "waiting", "recent"]);
  expect(b.layout.pages.me.regions.summary[1].p).toEqual({ weeks: 13 });
  await alt(lis(el, 1)[0], "ArrowUp");   // 맨 위에서 위로 = 바뀐 것 없음 = 요청 0
  expect(writes().length).toBe(2);
});

test("보내는 중이면 마지막 배치만 줄 세움 — PUT 2번(둘째 = 첫 응답 version) · 화면은 바로 새 배치", async () => {
  let release!: () => void;
  const gate = new Promise<void>(r => { release = r; });
  put = async body => { await gate; return json(200, { layout: body.layout, version: body.version + 1 }); };
  const el = await show();
  await alt(lis(el, 0)[0], "ArrowRight");   // 보내는 중
  expect(msg(el)).toBe(LAY_TEXT.saving);
  await alt(lis(el, 0)[2], "ArrowLeft");    // 줄 세움
  await alt(lis(el, 0)[3], "ArrowLeft");    // 줄 세운 것을 바꿈
  const want = ["summary", "decision", "axis", "principle", ...DEF.tabs.slice(4)];
  expect(keys(el, 0)).toEqual(want);
  put = body => json(200, { layout: body.layout, version: body.version + 1 });
  await act(async () => { release(); });
  await flush(); await flush();
  expect(writes().length).toBe(2);
  expect((writes()[1].body as typeof server).version).toBe(4);
  expect((writes()[1].body as typeof server).layout.pages.me.tabs).toEqual(want);
  expect(keys(el, 0)).toEqual(want);
  expect(msg(el)).toBe(LAY_TEXT.saved);
});

test("실패 = 마지막 저장 배치로 복원 + 한 줄(연결 실패·그 밖) · STALE = 서버 배치를 다시 받아 그대로", async () => {
  const el = await show();
  put = () => json(500, { code: "BOOM" });
  await alt(lis(el, 0)[0], "ArrowRight");
  expect(keys(el, 0)).toEqual(SWAP);
  expect(msg(el)).toBe(LAY_TEXT.fail);
  expect(el.querySelector("#lay-msg")!.className).toBe("ferr");
  put = () => { throw new TypeError("offline"); };
  await alt(lis(el, 0)[0], "ArrowRight");
  expect(keys(el, 0)).toEqual(SWAP);
  expect(msg(el)).toBe(LAY_TEXT.offline);
  server = lay(DEF.tabs, DEF.regions.summary, 7);
  put = () => json(409, { code: "LAYOUT-STALE", msg: "x" });
  await alt(lis(el, 0)[0], "ArrowRight");
  expect(keys(el, 0)).toEqual(DEF.tabs);
  expect(msg(el)).toBe(LAY_TEXT.stale);
  put = body => json(200, { layout: body.layout, version: body.version + 1 });
  await alt(lis(el, 0)[0], "ArrowRight");
  expect((writes()[writes().length - 1].body as typeof server).version).toBe(7);
});

test("기본으로 되돌리기 = DELETE 1 · 기본 배치 · 문구", async () => {
  const el = await show();
  await click(resetBtn(el));
  expect(writes()).toEqual([{ url: "/api/me/layout", method: "DELETE", body: undefined }]);
  expect(keys(el, 0)).toEqual(DEF.tabs);
  expect(msg(el)).toBe(LAY_TEXT.reset);
  expect(resetBtn(el).disabled).toBe(true);
});

test("끌어 놓기(마우스) — 끄는 동안 자리만 바꾸고 놓을 때 PUT 1 · 취소 = 요청 0 · 터치는 손잡이에서만", async () => {
  const el = await show();
  const rows = lis(el, 1);
  rows.forEach((li, i) => { li.getBoundingClientRect = () => ({ top: i * 50, bottom: i * 50 + 40, left: 0, right: 200, width: 200, height: 40 }) as DOMRect; });
  const ev = (li: Element, type: string, y: number, pointerType = "mouse", target: Element = li) =>
    act(async () => { target.dispatchEvent(Object.assign(new MouseEvent(type, { bubbles: true, clientY: y, button: 0 }), { pointerType, pointerId: 1 })); });
  await ev(rows[0], "pointerdown", 5, "touch");   // 손잡이 밖 터치 = 끌지 않음
  await ev(rows[0], "pointermove", 125, "touch");
  expect(keys(el, 1)[0]).toBe("heatmap");
  await ev(rows[0], "pointerdown", 5);
  await ev(rows[0], "pointermove", 125);
  expect(keys(el, 1)).toEqual(["kinds", "waiting", "heatmap", "recent"]);
  expect(writes().length).toBe(0);
  await ev(rows[0], "pointercancel", 125);
  expect(keys(el, 1)[0]).toBe("heatmap");
  await ev(rows[0], "pointerdown", 5, "touch", rows[0].querySelector("span")!);   // 손잡이 = 끈다
  await ev(rows[0], "pointermove", 125, "touch");
  await ev(rows[0], "pointerup", 125, "touch");
  await flush();
  expect((writes()[0].body as typeof server).layout.pages.me.regions.summary.map(s => s.c)).toEqual(["kinds", "waiting", "heatmap", "recent"]);
});
