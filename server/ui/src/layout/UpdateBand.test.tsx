// PC 앱 새 버전 띠 — 렌더·링크·나중에·6시간 타이머·창이 다시 보일 때 1시간 간격·겹침 없음·일반 브라우저와 실패는 띠 없음. fetch 는 가짜.
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { CHECK_EVERY_MS, DISMISS_KEY, LATEST_URL, VISIBLE_GAP_MS } from "../shared/desktopUpdate";
import { UpdateBand } from "./UpdateBand";

const APP = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) mycrm-desktop/0.1.1 Chrome/140.0.7339.41 Electron/45.1.0 Safari/537.36";
const CHROME = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.7339.41 Safari/537.36";
const rel = (tag: string) => ({ draft: false, prerelease: false, tag_name: tag, html_url: `https://github.com/WJY-ador/personal-mycrm/releases/tag/${tag}` });
let root: Root | null = null, host: HTMLElement, reply: () => Promise<Response>;
const f = vi.fn(async (_url: string, _init?: RequestInit) => reply());
const ok = (tag: string) => () => Promise.resolve(new Response(JSON.stringify(rel(tag)), { status: 200 }));
const flush = () => act(async () => { for (let i = 0; i < 3; i++) await Promise.resolve(); await new Promise(r => setTimeout(r, 0)); });
const band = () => host.querySelector(".band.update");
let visibility: DocumentVisibilityState = "visible";

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "Date"] });
  vi.setSystemTime(Date.UTC(2026, 10, 10, 3, 0, 0));
  f.mockClear(); reply = ok("v0.1.2"); vi.stubGlobal("fetch", f);
  visibility = "visible";
  vi.spyOn(document, "visibilityState", "get").mockImplementation(() => visibility);
  localStorage.clear();
  host = document.createElement("div"); document.body.replaceChildren(host);
});
afterEach(() => { act(() => root?.unmount()); root = null; vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

async function mount(ua: string) { await act(async () => { root = createRoot(host); root.render(<UpdateBand ua={ua} />); }); await flush(); }
async function seen(state: DocumentVisibilityState) { visibility = state; await act(async () => { document.dispatchEvent(new Event("visibilitychange")); }); await flush(); }

test("앱 창 + 새 버전 = 띠 · 문구 · 내려받기 = 릴리스 페이지(새 창 → 앱이 시스템 브라우저로) · 나중에 = 보조 버튼", async () => {
  await mount(APP);
  expect(f).toHaveBeenCalledTimes(1);
  expect(f.mock.calls[0][0]).toBe(LATEST_URL);
  expect(band()?.getAttribute("aria-label")).toBe("MyCRM 앱 업데이트");
  expect(band()?.querySelector(".update-text")?.textContent).toBe("MyCRM 앱 새 버전이 나왔어요. 지금 v0.1.1, 새 버전 v0.1.2.");
  const a = band()!.querySelector("a")!;
  expect([a.textContent, a.getAttribute("href"), a.target, a.rel, a.className, a.getAttribute("aria-label")]).toEqual(
    ["내려받기", "https://github.com/WJY-ador/personal-mycrm/releases/tag/v0.1.2", "_blank", "noopener noreferrer", "btn primary", "MyCRM 앱 v0.1.2 내려받기"]);
  const b = band()!.querySelector("button")!;
  expect([b.textContent, b.type, b.className, b.getAttribute("aria-label")]).toEqual(["나중에", "button", "secondary", "업데이트 안내 나중에 보기"]);
});

test("일반 브라우저 · 이미 최신 · 조회 실패 = 띠 없음(일반 브라우저는 조회도 없음)", async () => {
  await mount(CHROME);
  expect(f).not.toHaveBeenCalled(); expect(band()).toBeNull();
  act(() => root?.unmount()); root = null;
  reply = ok("v0.1.1"); await mount(APP);
  expect(band()).toBeNull();
  act(() => root?.unmount()); root = null;
  reply = () => Promise.reject(new TypeError("Failed to fetch")); await mount(APP);
  expect(band()).toBeNull(); expect(host.textContent).toBe("");
  act(() => root?.unmount()); root = null;
  reply = ok("v0.1.2-rc1"); await mount(APP);
  expect(band()).toBeNull();
});

test("나중에 = 닫고 기록 · 같은 버전은 24시간 뒤 다시 · 더 새 버전은 바로", async () => {
  await mount(APP);
  await act(async () => { band()!.querySelector("button")!.click(); });
  expect(band()).toBeNull();
  expect(JSON.parse(localStorage.getItem(DISMISS_KEY)!)).toEqual({ version: "v0.1.2", at: Date.now() });
  act(() => root?.unmount()); root = null;
  await mount(APP);                                            // 다시 열어도 24시간 안 = 없음
  expect(f).toHaveBeenCalledTimes(2); expect(band()).toBeNull();
  vi.setSystemTime(Date.now() + 24 * 60 * 60 * 1000);
  act(() => root?.unmount()); root = null;
  await mount(APP);
  expect(band()).not.toBeNull();
  await act(async () => { band()!.querySelector("button")!.click(); });
  reply = ok("v0.1.3");
  await act(async () => { vi.advanceTimersByTime(CHECK_EVERY_MS); }); await flush();
  expect(band()?.querySelector(".update-text")?.textContent).toContain("새 버전 v0.1.3");
});

test("저장소를 못 쓰면 이번 화면에서만 닫는다", async () => {
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("denied"); });
  await mount(APP);
  await act(async () => { band()!.querySelector("button")!.click(); });
  expect(band()).toBeNull();
});

test("6시간마다 다시 확인 · 실패해도 앞서 받은 띠는 그대로 · 언마운트하면 멈춘다", async () => {
  await mount(APP);
  expect(f).toHaveBeenCalledTimes(1);
  reply = () => Promise.reject(new TypeError("offline"));
  await act(async () => { vi.advanceTimersByTime(CHECK_EVERY_MS - 1); }); await flush();
  expect(f).toHaveBeenCalledTimes(1);
  await act(async () => { vi.advanceTimersByTime(1); }); await flush();
  expect(f).toHaveBeenCalledTimes(2); expect(band()).not.toBeNull();
  act(() => root?.unmount()); root = null;
  await act(async () => { vi.advanceTimersByTime(CHECK_EVERY_MS); }); await flush();
  expect(f).toHaveBeenCalledTimes(2);
});

test("창이 다시 보일 때 — 마지막 확인에서 1시간이 지났을 때만 · 숨을 때는 안 묻는다", async () => {
  await mount(APP);
  await seen("hidden"); await seen("visible");
  expect(f).toHaveBeenCalledTimes(1);                          // 1시간 안
  vi.setSystemTime(Date.now() + VISIBLE_GAP_MS);
  await seen("hidden");
  expect(f).toHaveBeenCalledTimes(1);
  await seen("visible");
  expect(f).toHaveBeenCalledTimes(2);
  await seen("visible");
  expect(f).toHaveBeenCalledTimes(2);                          // 방금 확인
});

test("확인이 겹치지 않는다 — 진행 중이면 타이머·다시 보임이 새 요청을 만들지 않는다", async () => {
  let finish: (r: Response) => void = () => {};
  reply = () => new Promise<Response>(r => { finish = r; });
  await mount(APP);
  vi.setSystemTime(Date.now() + VISIBLE_GAP_MS);
  await act(async () => { vi.advanceTimersByTime(CHECK_EVERY_MS); }); await seen("visible");
  expect(f).toHaveBeenCalledTimes(1);
  await act(async () => { finish(new Response(JSON.stringify(rel("v0.1.2")), { status: 200 })); }); await flush();
  expect(band()).not.toBeNull();
});
