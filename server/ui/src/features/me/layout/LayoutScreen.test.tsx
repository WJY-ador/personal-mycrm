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
  expect(lis(el, 0).map(li => li.children[0].textContent + li.children[1].textContent)).toEqual(["⠿기준 ", "⠿요약", "⠿결정 ", "⠿축 ", "⠿커스텀", "⠿사람 ", "⠿출처 "]);
  expect(lis(el, 0)[0].getAttribute("aria-label")).toBe("기준 — 1번째");
  expect(lis(el, 1).map(li => li.children[1].textContent)).toEqual(DEF.regions.summary.map(s => reg.components[s.c as keyof typeof reg.components].label));
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
  await click(el.querySelector('li[data-lay-key="principle"] button[aria-label="기준 아래로 이동"]'));   // 보내는 중
  expect(msg(el)).toBe(LAY_TEXT.saving);
  await click(el.querySelector('li[data-lay-key="principle"] button[aria-label="기준 아래로 이동"]'));
  const want = ["summary", "decision", "principle", "axis", ...DEF.tabs.slice(4)];
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
  await click(el.querySelector('li[data-lay-key="principle"] button[aria-label="기준 아래로 이동"]'));
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

test("위·아래 버튼으로 탭과 요약 순서를 바꾸고 기존 저장 경로를 쓴다", async () => {
  const el = await show();
  const tabDown = el.querySelector<HTMLButtonElement>('button[aria-label="기준 아래로 이동"]')!;
  tabDown.focus();
  await click(tabDown);
  expect(keys(el, 0).slice(0, 3)).toEqual(["summary", "principle", "decision"]);
  expect(document.activeElement).toBe(el.querySelector('li[data-lay-key="principle"] button[aria-label="기준 아래로 이동"]'));
  expect((writes()[0].body as typeof server).layout.pages.me.tabs.slice(0, 3)).toEqual(["summary", "principle", "decision"]);
  expect(msg(el)).toBe(LAY_TEXT.saved);

  await click(el.querySelector('button[aria-label="13주 글·활동 아래로 이동"]'));
  expect(keys(el, 1)).toEqual(["kinds", "heatmap", "waiting", "recent"]);
  expect((writes()[1].body as typeof server).layout.pages.me.regions.summary.map(s => s.c)).toEqual(["kinds", "heatmap", "waiting", "recent"]);
  expect(msg(el)).toBe(LAY_TEXT.saved);
});

test("목록 끝의 이동 버튼은 비활성화되어 저장하지 않는다", async () => {
  const el = await show();
  expect(el.querySelector<HTMLButtonElement>('button[aria-label="기준 위로 이동"]')!.disabled).toBe(true);
  expect(el.querySelector<HTMLButtonElement>('button[aria-label="출처 아래로 이동"]')!.disabled).toBe(true);
  expect(el.querySelector<HTMLButtonElement>('button[aria-label="13주 글·활동 위로 이동"]')!.disabled).toBe(true);
  expect(el.querySelector<HTMLButtonElement>('button[aria-label="최근 변경 아래로 이동"]')!.disabled).toBe(true);
  await click(el.querySelector('button[aria-label="기준 위로 이동"]'));
  expect(writes()).toHaveLength(0);
});

test("이동 후 사용한 버튼이 경계에서 비활성화되면 같은 항목의 반대 버튼에 초점을 둔다", async () => {
  const el = await show();
  await click(el.querySelector('li[data-lay-key="waiting"] button[aria-label="기다리는 결정 아래로 이동"]'));
  const row = el.querySelector('li[data-lay-key="waiting"]')!;
  expect(keys(el, 1)).toEqual(["heatmap", "kinds", "recent", "waiting"]);
  expect((row.querySelector('button[aria-label="기다리는 결정 아래로 이동"]') as HTMLButtonElement).disabled).toBe(true);
  expect(document.activeElement).toBe(row.querySelector('button[aria-label="기다리는 결정 위로 이동"]'));
});

// 자리 알림 — 옮길 때마다 항목 이름 + 새 자리(1부터)를 한 번. 읽기 = 늘 있는 #lay-pos(.sr) · 보이는 문구 = 옮긴 행 이름 바로 아래(aria-hidden).
// 저장 상태는 #lay-msg 가 따로.
const pos = (el: Element) => el.querySelector<HTMLElement>("#lay-pos")!;
const rowPos = (el: Element) => [...el.querySelectorAll<HTMLElement>("[data-lay-pos]")];
const row = (el: Element, k: string) => el.querySelector<HTMLElement>(`li[data-lay-key="${k}"]`)!;

test("위·아래 버튼으로 옮기면 옮긴 행 이름 아래에 이름과 새 자리(1부터)가 보이고 한 번 알린다 · 다른 행엔 없음 · 저장 상태는 따로 · 초점 그대로", async () => {
  const el = await show();
  const p = pos(el);
  expect(p.getAttribute("role")).toBe("status");
  expect(p.getAttribute("aria-live")).toBe("polite");
  expect(p.getAttribute("aria-atomic")).toBe("true");
  expect(p.classList.contains("sr")).toBe(true);   // 읽기 전용 — 보이는 문구는 행 안
  expect(p.parentElement!.classList.contains("paper")).toBe(true);   // .paper 직계 자식
  expect(p.previousElementSibling).toBe(el.querySelector("#lay-help"));   // 안내 문구 바로 다음
  expect(p.compareDocumentPosition(p.parentElement!.querySelector(":scope > section")!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();   // 첫 목록 위
  expect(p.textContent).toBe("");
  expect(rowPos(el)).toHaveLength(0);
  const button = el.querySelector<HTMLButtonElement>('li[data-lay-key="principle"] button[aria-label="기준 아래로 이동"]')!;
  button.focus();
  await click(button);
  expect(p.textContent).toBe("기준 2번째로 옮겼어요.");
  expect(p.children).toHaveLength(1);
  expect(msg(el)).toBe(LAY_TEXT.saved);
  expect(document.activeElement).toBe(el.querySelector('li[data-lay-key="principle"] button[aria-label="기준 아래로 이동"]'));
  expect(el.querySelectorAll('[role="status"]')).toHaveLength(2);   // 자리 알림 1 + 저장 줄 1
  // 보이는 문구 = 옮긴 행(기준)의 이름 바로 아래 하나 · aria-hidden(중복 읽기 없음) · 다른 행엔 없음 · 행 이름(aria-label·버튼)은 그대로
  const inl = rowPos(el);
  expect(inl).toHaveLength(1);
  expect(inl[0].textContent).toBe("기준 2번째로 옮겼어요.");
  expect(inl[0].getAttribute("aria-hidden")).toBe("true");
  expect(inl[0].closest("li")).toBe(row(el, "principle"));
  expect(inl[0].parentElement!.textContent!.startsWith("기준")).toBe(true);   // 이름 span 안, 이름 뒤
  expect(inl[0].parentElement!.lastElementChild).toBe(inl[0]);
  expect(inl[0].closest("[role],[aria-live]")).toBeNull();
  expect(row(el, "principle").getAttribute("aria-label")).toBe("기준 — 2번째");
  for (const k of SWAP.filter(k => k !== "principle")) expect(row(el, k).querySelector("[data-lay-pos]")).toBeNull();
  for (const li of lis(el, 1)) expect(li.querySelector("[data-lay-pos]")).toBeNull();

  await click(el.querySelector('button[aria-label="13주 글·활동 아래로 이동"]'));
  expect(p.textContent).toBe("13주 글·활동 2번째로 옮겼어요.");
  // 다른 목록 행으로 옮기면 문구도 그 행으로 — 앞 행(기준)에선 사라진다
  expect(rowPos(el)).toHaveLength(1);
  expect(rowPos(el)[0].closest("li")).toBe(row(el, "heatmap"));
  expect(rowPos(el)[0].textContent).toBe("13주 글·활동 2번째로 옮겼어요.");
  expect(row(el, "principle").querySelector("[data-lay-pos]")).toBeNull();
});

test("저장이 늦게 끝나도 자리 알림은 다시 그리지 않는다(중복 알림 없음) · 줄 세운 이동은 마지막 자리", async () => {
  let release!: () => void;
  const gate = new Promise<void>(r => { release = r; });
  put = async body => { await gate; return json(200, { layout: body.layout, version: body.version + 1 }); };
  const el = await show();
  await click(el.querySelector('li[data-lay-key="principle"] button[aria-label="기준 아래로 이동"]'));
  expect(pos(el).textContent).toBe("기준 2번째로 옮겼어요.");
  expect(msg(el)).toBe(LAY_TEXT.saving);
  await click(el.querySelector('li[data-lay-key="principle"] button[aria-label="기준 아래로 이동"]'));
  expect(pos(el).textContent).toBe("기준 3번째로 옮겼어요.");
  const node = pos(el).firstElementChild;
  put = body => json(200, { layout: body.layout, version: body.version + 1 });
  await act(async () => { release(); });
  await flush(); await flush();
  expect(msg(el)).toBe(LAY_TEXT.saved);
  expect(pos(el).firstElementChild).toBe(node);
  expect(pos(el).textContent).toBe("기준 3번째로 옮겼어요.");
  expect(rowPos(el).map(s => [s.closest("li")!.dataset.layKey, s.textContent])).toEqual([["principle", "기준 3번째로 옮겼어요."]]);   // 저장 성공 = 행 안 문구 유지
});

test("저장 실패·연결 실패·STALE 로 되돌리면 자리 알림을 지우고 저장 줄만 실패를 알린다", async () => {
  let release!: () => void;
  const gate = new Promise<void>(r => { release = r; });
  put = async () => { await gate; return json(500, { code: "BOOM" }); };
  const el = await show();
  await click(el.querySelector('li[data-lay-key="principle"] button[aria-label="기준 아래로 이동"]'));
  expect(pos(el).textContent).toBe("기준 2번째로 옮겼어요.");
  await act(async () => { release(); });
  await flush(); await flush();
  expect(keys(el, 0)).toEqual(SWAP);
  expect(pos(el).textContent).toBe("");
  expect(rowPos(el)).toHaveLength(0);
  expect(msg(el)).toBe(LAY_TEXT.fail);

  put = () => { throw new TypeError("offline"); };
  await alt(lis(el, 0)[0], "ArrowRight");
  expect(pos(el).textContent).toBe("");
  expect(msg(el)).toBe(LAY_TEXT.offline);

  server = lay(DEF.tabs, DEF.regions.summary, 7);
  put = () => json(409, { code: "LAYOUT-STALE", msg: "x" });
  await alt(lis(el, 0)[0], "ArrowRight");
  expect(keys(el, 0)).toEqual(DEF.tabs);
  expect(pos(el).textContent).toBe("");
  expect(rowPos(el)).toHaveLength(0);
  expect(msg(el)).toBe(LAY_TEXT.stale);

  put = body => json(200, { layout: body.layout, version: body.version + 1 });
  await alt(lis(el, 0)[0], "ArrowRight");
  expect(pos(el).textContent).toBe("요약 2번째로 옮겼어요.");
  expect(rowPos(el).map(s => s.closest("li")!.dataset.layKey)).toEqual(["summary"]);
  expect(msg(el)).toBe(LAY_TEXT.saved);
});

test("기본으로 되돌리기는 자리 알림을 지운다", async () => {
  const el = await show();
  await click(el.querySelector('button[aria-label="13주 글·활동 아래로 이동"]'));   // 탭은 SWAP 그대로 = 기본과 달라 되돌리기 켜짐
  expect(pos(el).textContent).toBe("13주 글·활동 2번째로 옮겼어요.");
  expect(resetBtn(el).disabled).toBe(false);
  expect(rowPos(el)).toHaveLength(1);
  await click(resetBtn(el));
  expect(pos(el).textContent).toBe("");
  expect(rowPos(el)).toHaveLength(0);
  expect(msg(el)).toBe(LAY_TEXT.reset);
});

test("경계로 옮기면 마지막 자리를 알리고 반대 버튼에 초점 · 같은 문구도 새 노드로 다시 알린다 · 비활성 버튼은 알리지 않는다", async () => {
  const el = await show();
  const p = pos(el);
  await click(el.querySelector('li[data-lay-key="waiting"] button[aria-label="기다리는 결정 아래로 이동"]'));
  expect(p.textContent).toBe("기다리는 결정 4번째로 옮겼어요.");
  expect(document.activeElement).toBe(el.querySelector('li[data-lay-key="waiting"] button[aria-label="기다리는 결정 위로 이동"]'));
  const first = p.firstElementChild;
  await click(el.querySelector('li[data-lay-key="waiting"] button[aria-label="기다리는 결정 위로 이동"]'));
  expect(p.textContent).toBe("기다리는 결정 3번째로 옮겼어요.");
  await click(el.querySelector('li[data-lay-key="waiting"] button[aria-label="기다리는 결정 아래로 이동"]'));
  expect(p.textContent).toBe("기다리는 결정 4번째로 옮겼어요.");
  expect(p.firstElementChild).not.toBe(first);   // 같은 문구도 새 노드 = 다시 읽힌다
  const before = p.firstElementChild;
  await click(el.querySelector('li[data-lay-key="waiting"] button[aria-label="기다리는 결정 아래로 이동"]'));   // 비활성
  expect(p.firstElementChild).toBe(before);
  expect(writes()).toHaveLength(3);
  await click(el.querySelector('li[data-lay-key="heatmap"] button[aria-label="13주 글·활동 위로 이동"]'));   // 첫 자리 비활성
  expect(p.firstElementChild).toBe(before);
  expect(writes()).toHaveLength(3);
});

test("Alt + 화살표로 옮기면 같은 자리 알림 · 경계에서 더 못 가면 알리지 않는다", async () => {
  const el = await show();
  await alt(lis(el, 0)[0], "ArrowUp");   // 맨 앞에서 앞으로 = 바뀐 것 없음
  expect(pos(el).textContent).toBe("");
  expect(writes()).toHaveLength(0);
  await alt(lis(el, 0)[0], "ArrowRight");
  expect(keys(el, 0).slice(0, 2)).toEqual(["summary", "principle"]);
  expect(pos(el).textContent).toBe("기준 2번째로 옮겼어요.");
  expect(msg(el)).toBe(LAY_TEXT.saved);
  const last = lis(el, 1)[3];
  await alt(last, "ArrowDown");   // 맨 끝에서 뒤로 = 그대로
  expect(pos(el).textContent).toBe("기준 2번째로 옮겼어요.");
  await alt(last, "ArrowUp");
  expect(pos(el).textContent).toBe("최근 변경 3번째로 옮겼어요.");
  expect(rowPos(el).map(s => [s.closest("li")!.dataset.layKey, s.textContent])).toEqual([["recent", "최근 변경 3번째로 옮겼어요."]]);
});

test("끌어 놓기(마우스)로 놓으면 자리 알림 · 끄는 중·취소는 알리지 않는다", async () => {
  const el = await show();
  const rows = lis(el, 1);
  rows.forEach((li, i) => { li.getBoundingClientRect = () => ({ top: i * 50, bottom: i * 50 + 40, left: 0, right: 200, width: 200, height: 40 }) as DOMRect; });
  const ev = (li: Element, type: string, y: number) =>
    act(async () => { li.dispatchEvent(Object.assign(new MouseEvent(type, { bubbles: true, clientY: y, button: 0 }), { pointerType: "mouse", pointerId: 1 })); });
  await ev(rows[0], "pointerdown", 5);
  await ev(rows[0], "pointermove", 125);
  expect(pos(el).textContent).toBe("");
  await ev(rows[0], "pointercancel", 125);
  expect(pos(el).textContent).toBe("");
  expect(rowPos(el)).toHaveLength(0);
  await ev(rows[0], "pointerdown", 5);
  await ev(rows[0], "pointermove", 125);
  await ev(rows[0], "pointerup", 125);
  await flush();
  expect(keys(el, 1)).toEqual(["kinds", "waiting", "heatmap", "recent"]);
  expect(pos(el).textContent).toBe("13주 글·활동 3번째로 옮겼어요.");
  expect(rowPos(el).map(s => [s.closest("li")!.dataset.layKey, s.textContent])).toEqual([["heatmap", "13주 글·활동 3번째로 옮겼어요."]]);
  expect(msg(el)).toBe(LAY_TEXT.saved);
});

test("네이티브 버튼이 Enter와 Space의 기본 활성화를 막지 않고 클릭과 같은 동작을 한다", async () => {
  const el = await show();
  const button = el.querySelector<HTMLButtonElement>('button[aria-label="기준 아래로 이동"]')!;
  expect(button.tagName).toBe("BUTTON");
  expect(button.type).toBe("button");
  button.focus();
  for (const key of ["Enter", " "]) {
    const event = new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true });
    button.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(false);
    await click(button); // JSDOM에서는 네이티브 키 활성화가 생성되지 않아 실제 click을 대리한다.
  }
  expect(keys(el, 0).slice(0, 3)).toEqual(["summary", "decision", "principle"]);
  expect(writes()).toHaveLength(2);
});

test("이동 버튼의 마우스 pointerdown은 행 드래그를 시작하지 않는다", async () => {
  const el = await show();
  const row = el.querySelector('li[data-lay-key="principle"]')!;
  const button = row.querySelector('button[aria-label="기준 아래로 이동"]')!;
  await act(async () => {
    button.dispatchEvent(Object.assign(new MouseEvent("pointerdown", { bubbles: true, button: 0 }), { pointerType: "mouse", pointerId: 1 }));
  });
  expect(row.classList.contains("dragging")).toBe(false);
  expect(keys(el, 0).slice(0, 2)).toEqual(["principle", "summary"]);
  expect(writes()).toHaveLength(0);
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
