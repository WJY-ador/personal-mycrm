// 「활동」(옛 test_web_import.py 정적 절 + 화면 동작을 옮김) — 목록·거르기(주소로) · 현황 접힘(30일 = 상태, 그 밖 = 받음) · 설명 문장 ·
// 활동 하나(사람·축·메모·판 이력) · 원문 = 127.0.0.1 링크 하나뿐(가져오기 0)·포트는 이 브라우저에만 · 휴대폰 = 안내만 · 축 하나 · [삭제]
import { act } from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { queryClient } from "../../shared/queries";
import { calls, click, installFetch, json, serve, text } from "../../test/fakeServer";
import { byText, hideScreen, reload, showScreen } from "../../test/showScreen";
import sample from "./activity.sample.json";
import { ME_NOTICE, RAW_PORT_KEY } from "./text";

const RAW = "a".repeat(48);
const S = {
  user: { nav: "new" }, switches: { trash: true }, activity_ui: { actions: { like: "좋아요", comment: "댓글" }, providers: { sns: "SNS" }, pending_days: 30 },
  activity: { ...sample.agg, period: "30d", notice: ME_NOTICE }, people: [{ id: "p_p1", alias: "사람-P1" }], sources: [], items: [], definitions: [],
};
const ONE = { ...sample.one, raw: { raw_id: RAW, local_only: true } };
const confirm = vi.fn((_ask?: string) => true);
const show = (hash: string, args: string[], st: object = S) => showScreen("activity", hash, args, st);

beforeEach(() => {
  installFetch(); queryClient.clear(); reload.mockClear(); confirm.mockReturnValue(true);
  vi.stubGlobal("confirm", confirm);
  try { localStorage.clear(); } catch { /* 없음 */ }
  serve((url, m) => {
    if (m === "POST") return json(200, {});
    if (url.startsWith("/api/activities?") || url === "/api/activities") return json(200, url.includes("cursor=c2") ? { activities: [], next_cursor: "" } : { ...sample.list, next_cursor: "c2" });
    if (url.startsWith("/api/activities/")) return json(200, ONE);
    if (url.startsWith("/api/me/aggregate")) return json(200, { ...sample.agg, total: 77 });
    if (url.startsWith("/api/axes/")) return json(200, sample.axis);
    return json(404, {});
  });
});
afterEach(() => { hideScreen(); vi.unstubAllGlobals(); });

test("목록 — 줄(행동·날짜·출처·사람·축) · [더 보기] = 커서 · 거르기 = 주소로(사람·출처·축은 그대로)", async () => {
  const el = await show("#_obj/activity/list/person=p_p1&action=like", ["activity", "list", "person=p_p1&action=like"]);
  expect(calls[0].url).toBe("/api/activities?action=like&person=p_p1");
  expect(el.textContent).toContain("사람 「사람-P1」로 거른 목록");
  expect(el.querySelector("details")).toBeNull();   // 거른 목록 = 현황 접힘 없음
  expect(text(el, "li.actrow .chip")).toEqual(["좋아요"]);
  await click(byText(el, "button", "더 보기")[0]);
  expect(calls.at(-1)!.url).toBe("/api/activities?action=like&person=p_p1&cursor=c2");
  const sel = el.querySelector('select[name="dated"]') as HTMLSelectElement;
  await act(async () => { sel.value = "no"; sel.dispatchEvent(new Event("change", { bubbles: true })); });
  expect(location.hash).toBe("#_obj/activity/list/person=p_p1&action=like&dated=no");
});

test("현황 접힘 — 설명 문장(서버 notice) · 30일 = 상태 그대로(요청 0) · 7일 = 그 기간을 받음 · 막대·「?」 도움말", async () => {
  const el = await show("#_obj/activity", ["activity", "", ""]);
  expect(el.textContent).toContain(ME_NOTICE);
  const d = el.querySelector("details")!;
  await act(async () => { d.open = true; d.dispatchEvent(new Event("toggle")); });
  expect(calls.filter(c => c.url.startsWith("/api/me/aggregate"))).toEqual([]);
  expect(el.textContent).toContain("행동별");
  expect(el.querySelectorAll('summary[aria-label="계산 방법"]').length).toBeGreaterThan(1);
  expect(el.querySelector('a[href="#_obj/activity/list/dated=no"]')).not.toBeNull();
  await click(byText(el, "button", "최근 7일")[0]);
  expect(calls.filter(c => c.url.startsWith("/api/me/aggregate")).map(c => c.url)).toEqual(["/api/me/aggregate?period=7d"]);
  expect(el.textContent).toContain("77");
  expect(byText(el, "button", "최근 7일")[0].getAttribute("aria-pressed")).toBe("true");
});

test("활동 하나 — 사람·축 칩 · 메모 = 「나」 글 주소 · 판 이력 · 원문 = 127.0.0.1 링크 하나(가져오기 0) · 포트 = localStorage 키 하나", async () => {
  const el = await show("#_obj/activity/a_a2", ["activity", "a_a2", ""]);
  expect(text(el, ".chip.axis").length).toBeGreaterThan(0);
  expect(el.querySelector('a[href="#_me/journal/r_sample"]')!.textContent).toBe("견본 메모");
  expect(el.textContent).toContain("지금 보는 판");
  const raw = [...el.querySelectorAll("a")].filter(a => a.href.includes("127.0.0.1"));
  expect(raw.map(a => [a.getAttribute("href"), a.rel, a.target])).toEqual([[`http://127.0.0.1:8790/raw/${RAW}`, "noopener noreferrer", "_blank"]]);
  expect(calls.every(c => !c.url.includes("127.0.0.1"))).toBe(true);
  expect(el.textContent).toContain("원문을 보관한 PC에서 열 수 있습니다");
  const set = vi.spyOn(Storage.prototype, "setItem");
  const inp = el.querySelector("#raw-port") as HTMLInputElement;
  const setV = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
  await act(async () => { setV.call(inp, "99"); inp.dispatchEvent(new Event("input", { bubbles: true })); });
  await click(byText(el, "button", "저장")[0]);
  expect(el.textContent).toContain("1024~65535 사이 숫자를 적어 주세요.");
  await act(async () => { setV.call(inp, "8801"); inp.dispatchEvent(new Event("input", { bubbles: true })); });
  await click(byText(el, "button", "저장")[0]);
  expect(set.mock.calls).toEqual([[RAW_PORT_KEY, "8801"]]);
  expect(el.querySelector('a[href^="http://127.0.0.1:8801/raw/"]')).not.toBeNull();
});

test("휴대폰 = 원문 버튼 대신 안내(링크 0) · 원문 ID 없음 = 안내", async () => {
  vi.stubGlobal("matchMedia", () => ({ matches: true }));
  const el = await show("#_obj/activity/a_a2", ["activity", "a_a2", ""]);
  expect([...el.querySelectorAll("a")].filter(a => a.href.includes("127.0.0.1"))).toEqual([]);
  expect((byText(el, "button", "원문을 보관한 PC에서 열 수 있습니다")[0] as HTMLButtonElement).disabled).toBe(true);
});

test("[삭제] — 휴지통 켜짐 + 새 탐색일 때만 · 확인 → 휴지통으로 → 목록 머리에 결과 한 줄", async () => {
  let el = await show("#_obj/activity/a_a2", ["activity", "a_a2", ""], { ...S, switches: { trash: false } });
  expect(byText(el, "button", "삭제")).toEqual([]);
  hideScreen();
  el = await show("#_obj/activity/a_a2", ["activity", "a_a2", ""], { ...S, user: { nav: "old" } });   // 옛 탐색 = [삭제] 0
  expect(byText(el, "button", "삭제")).toEqual([]);
  hideScreen();
  el = await show("#_obj/activity/a_a2", ["activity", "a_a2", ""]);
  await click(byText(el, "button", "삭제")[0]);
  expect(calls.filter(c => c.method === "POST")).toEqual([{ url: "/api/trash/move", method: "POST", body: { kind: "activity", id: "a_a2" } }]);
  expect(location.hash).toBe("#_obj/activity");
  el = await show("#_obj/activity", ["activity", "", ""]);
  expect(text(el, "p.fok")).toEqual(["휴지통으로 옮겼어요."]);
});

test("축 하나 — 활동 · 내 글(「나」 주소) · 가리키는 판단·기준(옛 주소 → 새 자리)", async () => {
  const el = await show("#_obj/axis/i_x1", ["axis", "i_x1", ""]);
  expect(calls.map(c => c.url)).toEqual(["/api/axes/i_x1/context"]);
  expect(el.querySelector("h2.title")!.textContent).toBe("축 X1");
  expect(el.querySelector('a[href="#_me/journal/r_sample"]')).not.toBeNull();
  expect(el.querySelector('a[href="#structure/od_principles/i_sample"]')).not.toBeNull();
});
