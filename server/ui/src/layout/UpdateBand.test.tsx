// PC 앱 새 버전 띠 — 렌더·링크·나중에·6시간 타이머·창이 다시 보일 때 1시간 간격·겹침 없음·일반 브라우저와 실패는 띠 없음. fetch 는 가짜.
// 앱 다리(window.mycrmDesktop.update)가 있으면 앱 상태만 그린다 — 다리 시험은 아래 절. 다리도 가짜.
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
afterEach(() => {
  act(() => root?.unmount()); root = null; vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks();
  delete (window as { mycrmDesktop?: unknown }).mycrmDesktop;
});

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

// ── 앱 다리 ──
const ST = { inApp: true, phase: "available", current: "0.2.0", version: "0.2.1", percent: null, reason: null };
function fakeBridge(first: unknown = ST) {
  const subs = new Set<(s: unknown) => void>();
  const api = {
    get: vi.fn(async (..._a: unknown[]) => first),
    onChange: vi.fn((cb: (s: unknown) => void) => { subs.add(cb); return () => { subs.delete(cb); }; }),
    download: vi.fn(async (..._a: unknown[]) => {}),
    install: vi.fn(async (..._a: unknown[]) => {}),
  };
  (window as { mycrmDesktop?: unknown }).mycrmDesktop = { update: api };
  const emit = async (s: unknown) => { await act(async () => { for (const cb of subs) cb(s); }); await flush(); };
  return { api, subs, emit };
}
const text = () => band()?.querySelector(".update-text")?.textContent;
const buttons = () => [...band()!.querySelectorAll("button, a")].map(e => e.textContent);
const press = async (label: string) => {
  const el = [...band()!.querySelectorAll("button")].find(b => b.textContent === label)!;
  await act(async () => { el.click(); }); await flush();
};

test("다리 = 앱 상태를 그린다 · GitHub 직접 조회 없음 · 일반 UA 여도 다리를 따른다 · 구독하고 언마운트 때 해제", async () => {
  const { api, subs } = fakeBridge();
  await mount(CHROME);
  expect(f).not.toHaveBeenCalled();
  expect(api.get).toHaveBeenCalledTimes(1); expect(api.onChange).toHaveBeenCalledTimes(1); expect(subs.size).toBe(1);
  expect(band()?.getAttribute("role")).toBe("region");
  expect(band()?.getAttribute("aria-label")).toBe("MyCRM 앱 업데이트");
  expect(band()?.hasAttribute("aria-live")).toBe(false);
  expect(text()).toBe("MyCRM 앱 새 버전이 나왔어요. 지금 v0.2.0, 새 버전 v0.2.1.");
  expect(buttons()).toEqual(["지금 업데이트", "나중에"]);
  expect(band()!.querySelector("button.primary")?.getAttribute("aria-label")).toBe("MyCRM 앱 v0.2.1 지금 업데이트");
  await act(async () => { vi.advanceTimersByTime(CHECK_EVERY_MS); }); await flush();
  expect(f).not.toHaveBeenCalled();
  act(() => root?.unmount()); root = null;
  expect(subs.size).toBe(0);
});

test("다리 상태별 띠 — 지금 업데이트 = download() · 받는 중 진행률 · 다시 시작 = install() · 오류 = 다시 시도·직접 내려받기 · idle·checking = 없음", async () => {
  const { api, emit } = fakeBridge();
  await mount(APP);
  await press("지금 업데이트");
  expect(api.download).toHaveBeenCalledTimes(1); expect(api.download).toHaveBeenCalledWith();
  await emit({ ...ST, phase: "downloading", percent: null });
  expect(text()).toBe("새 버전을 받고 있어요."); expect(band()!.querySelector(".update-acts")).toBeNull();
  await emit({ ...ST, phase: "downloading", percent: 40 });
  expect(text()).toBe("새 버전을 받고 있어요. 40%"); expect(buttons()).toEqual([]);
  await emit({ ...ST, phase: "downloaded" });
  expect(text()).toBe("새 버전을 받았어요. 다시 시작하면 설치돼요.");
  expect(buttons()).toEqual(["다시 시작", "나중에"]);
  await press("다시 시작");
  expect(api.install).toHaveBeenCalledTimes(1); expect(api.install).toHaveBeenCalledWith();
  await emit({ ...ST, phase: "error", reason: "install" });
  expect(text()).toBe("업데이트를 설치하지 못했어요.");
  await emit({ ...ST, phase: "error", version: null, reason: "network" });
  expect(text()).toBe("업데이트를 받지 못했어요.");
  expect(buttons()).toEqual(["다시 시도", "직접 내려받기"]);
  const a = band()!.querySelector("a")!;
  expect([a.getAttribute("href"), a.target, a.rel, a.className]).toEqual(["https://github.com/WJY-ador/personal-mycrm/releases", "_blank", "noopener noreferrer", "btn"]);
  await press("다시 시도");
  expect(api.download).toHaveBeenCalledTimes(2); expect(api.download).toHaveBeenLastCalledWith();
  for (const phase of ["idle", "checking"]) { await emit({ ...ST, phase, version: null }); expect(band()).toBeNull(); }
  expect(f).not.toHaveBeenCalled();
});

test("다리 inApp=false — 지금 문구 · 내려받기 = 웹 상수로 만든 릴리스 페이지 · 나중에", async () => {
  fakeBridge({ ...ST, inApp: false });
  await mount(APP);
  expect(text()).toBe("MyCRM 앱 새 버전이 나왔어요. 지금 v0.2.0, 새 버전 v0.2.1.");
  expect(buttons()).toEqual(["내려받기", "나중에"]);
  const a = band()!.querySelector("a")!;
  expect([a.getAttribute("href"), a.target, a.rel, a.className, a.getAttribute("aria-label")]).toEqual(
    ["https://github.com/WJY-ador/personal-mycrm/releases/tag/v0.2.1", "_blank", "noopener noreferrer", "btn primary", "MyCRM 앱 v0.2.1 내려받기"]);
  expect(f).not.toHaveBeenCalled();
});

test("다리 나중에 — v 붙은 꼴로 기록 · 같은 버전 24시간 · 옛 기록(v 붙음)도 맞는다 · 받는 중은 나중에와 상관없이 보인다", async () => {
  const { emit } = fakeBridge();
  await mount(APP);
  await press("나중에");
  expect(band()).toBeNull();
  expect(JSON.parse(localStorage.getItem(DISMISS_KEY)!)).toEqual({ version: "v0.2.1", at: Date.now() });
  await emit({ ...ST });                                       // 같은 버전 다시 알림 = 숨김 유지
  expect(band()).toBeNull();
  await emit({ ...ST, phase: "downloading", percent: 5 });
  expect(text()).toBe("새 버전을 받고 있어요. 5%");
  await emit({ ...ST, version: "0.2.2" });                     // 더 새 버전 = 바로
  expect(text()).toContain("새 버전 v0.2.2");
  act(() => root?.unmount()); root = null;
  localStorage.setItem(DISMISS_KEY, JSON.stringify({ version: "v0.2.1", at: Date.now() }));   // 옛 길이 남긴 기록
  fakeBridge();
  const timeout = vi.spyOn(window, "setTimeout");
  await mount(APP);
  expect(band()).toBeNull();
  const wake = timeout.mock.calls.find(c => c[1] === 24 * 60 * 60 * 1000)?.[0] as (() => void) | undefined;   // 알림이 없어도 24시간 뒤 다시
  expect(wake).toBeTypeOf("function");
  vi.setSystemTime(Date.now() + 24 * 60 * 60 * 1000);
  await act(async () => { wake!(); }); await flush();
  expect(text()).toContain("새 버전 v0.2.1");
});

test("다리 값 모양이 틀리면 띠 없음(오류 문구 없음) · 다리 호출이 던지거나 거절해도 화면은 그대로", async () => {
  const { api, emit } = fakeBridge({ ...ST, version: "v0.2.1" });
  await mount(APP);
  expect(band()).toBeNull(); expect(host.textContent).toBe(""); expect(f).not.toHaveBeenCalled();
  await emit(ST);
  expect(band()).not.toBeNull();
  await emit({ ...ST, inApp: false, phase: "downloading", percent: 3 });   // 계약 밖 조합 = 띠를 내린다
  expect(band()).toBeNull();
  await emit(ST);
  api.download.mockImplementation(async () => { throw new Error("ipc"); });
  await press("지금 업데이트");
  api.download.mockImplementation(() => { throw new Error("sync"); });
  await press("지금 업데이트");
  expect(text()).toBe("MyCRM 앱 새 버전이 나왔어요. 지금 v0.2.0, 새 버전 v0.2.1.");
  act(() => root?.unmount()); root = null;
  const b = fakeBridge();
  b.api.get.mockImplementation(async () => { throw new Error("ipc"); });
  b.api.onChange.mockImplementation(() => { throw new Error("ipc"); });
  await mount(APP);
  expect(band()).toBeNull(); expect(f).not.toHaveBeenCalled();
  expect(() => act(() => root?.unmount())).not.toThrow(); root = null;
});

test("다리 — 먼저 온 알림이 늦게 끝난 get() 보다 우선 · 반쪽 다리는 옛 길", async () => {
  let done: (s: unknown) => void = () => {};
  const { api, emit } = fakeBridge();
  api.get.mockImplementation(() => new Promise(r => { done = r; }));
  await mount(APP);
  await emit({ ...ST, phase: "downloading", percent: 70 });
  await act(async () => { done(ST); }); await flush();
  expect(text()).toBe("새 버전을 받고 있어요. 70%");
  act(() => root?.unmount()); root = null;
  (window as { mycrmDesktop?: unknown }).mycrmDesktop = { update: { get: api.get, onChange: api.onChange } };
  reply = ok("v0.1.2"); await mount(APP);
  expect(f).toHaveBeenCalledTimes(1);
  expect(text()).toBe("MyCRM 앱 새 버전이 나왔어요. 지금 v0.1.1, 새 버전 v0.1.2.");
});
