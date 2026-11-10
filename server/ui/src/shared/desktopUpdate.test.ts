// PC 앱 새 버전 띠 판정 — 순수 함수(UA·버전 비교·릴리스 응답 검사·나중에 24시간) + 조회 실패 = null. 실제 네트워크는 부르지 않는다.
// 앱 다리(계약 0.2.2) — 다리 판정 · 상태 모양 검사 · 릴리스 페이지 주소 · 앱 상태로 띄울지.
import { afterEach, expect, test, vi } from "vitest";
import { DISMISS_KEY, LATEST_URL, SNOOZE_MS, desktopBridge, fetchLatest, installedVersion, newer, parseRelease, parseState, readDismissed,
  releasePage, saveDismissed, shouldShow, shouldShowApp } from "./desktopUpdate";

const MAC = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko)";
const APP = `${MAC} mycrm-desktop/0.1.1 Chrome/140.0.7339.41 Electron/45.1.0 Safari/537.36`;
const OK = { draft: false, prerelease: false, tag_name: "v0.1.2", html_url: "https://github.com/WJY-ador/personal-mycrm/releases/tag/v0.1.2" };
const REL = { version: "v0.1.2", url: OK.html_url };
const T = Date.UTC(2026, 10, 10, 3, 0, 0);

afterEach(() => { vi.unstubAllGlobals(); localStorage.clear(); });

test("설치 버전 — Electron 과 앱 토큰(name·productName)이 둘 다 있을 때만", () => {
  expect(installedVersion(APP)).toBe("0.1.1");
  expect(installedVersion(`${MAC} MyCRM/0.1.3 Chrome/140.0.7339.41 Electron/45.1.0 Safari/537.36`)).toBe("0.1.3");
  expect(installedVersion(`${MAC} Chrome/140.0.7339.41 Safari/537.36`)).toBeNull();                 // 일반 Chrome
  expect(installedVersion(`${MAC} Chrome/140.0.7339.41 Electron/45.1.0 Safari/537.36`)).toBeNull(); // Electron, 앱 토큰 없음
  expect(installedVersion(`${MAC} mycrm-desktop/0.1.1 Chrome/140.0.7339.41 Safari/537.36`)).toBeNull(); // 앱 토큰만, Electron 아님
  expect(installedVersion(`${MAC} xmycrm-desktop/0.1.1 Electron/45.1.0`)).toBeNull();                  // 다른 이름의 일부
  expect(installedVersion(`${MAC} mycrm-desktop/0.1 Electron/45.1.0`)).toBeNull();                     // X.Y.Z 아님
  expect(installedVersion("")).toBeNull();
});

test("버전 비교 — 숫자로(0.1.10 > 0.1.9), 같거나 낮거나 형식이 다르면 false", () => {
  expect(newer("v0.1.2", "0.1.1")).toBe(true);
  expect(newer("v0.1.10", "0.1.9")).toBe(true);
  expect(newer("v1.0.0", "0.9.9")).toBe(true);
  expect(newer("v0.1.1", "0.1.1")).toBe(false);
  expect(newer("v0.1.0", "0.1.1")).toBe(false);
  expect(newer("v0.1.2-beta", "0.1.1")).toBe(false);
  expect(newer("v0.1.2", "")).toBe(false);
});

test("릴리스 응답 — 안정 릴리스만, draft·prerelease·태그 형식·주소 검사", () => {
  expect(parseRelease(OK)).toEqual(REL);
  expect(parseRelease({ ...OK, draft: true })).toBeNull();
  expect(parseRelease({ ...OK, prerelease: true })).toBeNull();
  for (const tag_name of ["0.1.2", "v0.1.2-rc1", "v0.1", "", 12]) expect(parseRelease({ ...OK, tag_name })).toBeNull();
  for (const html_url of ["https://github.com/other/repo/releases/tag/v0.1.2", "https://evil.example/WJY-ador/personal-mycrm/releases/",
    "http://github.com/WJY-ador/personal-mycrm/releases/tag/v0.1.2", "https://github.com/WJY-ador/personal-mycrm/releases/../../x",
    "https://github.com/WJY-ador/personal-mycrm/releasesX", "javascript:alert(1)", "", null])
    expect(parseRelease({ ...OK, html_url })).toBeNull();
  for (const bad of [null, undefined, "x", 1, []]) expect(parseRelease(bad)).toBeNull();
});

test("띄울지 — 새 버전 · 같은 버전 나중에는 24시간 · 더 새 버전은 바로", () => {
  expect(shouldShow("0.1.1", REL, null, T)).toBe(true);
  expect(shouldShow("0.1.2", REL, null, T)).toBe(false);
  expect(shouldShow("0.1.3", REL, null, T)).toBe(false);
  expect(shouldShow(null, REL, null, T)).toBe(false);
  expect(shouldShow("0.1.1", null, null, T)).toBe(false);
  const d = { version: "v0.1.2", at: T };
  expect(shouldShow("0.1.1", REL, d, T + 1000)).toBe(false);
  expect(shouldShow("0.1.1", REL, d, T + SNOOZE_MS - 1)).toBe(false);
  expect(shouldShow("0.1.1", REL, d, T + SNOOZE_MS)).toBe(true);
  expect(shouldShow("0.1.1", { version: "v0.1.3", url: REL.url }, d, T + 1000)).toBe(true);
  expect(shouldShow("0.1.1", REL, { version: "v0.1.2", at: T + 5000 }, T)).toBe(true);   // 미래 시각 기록 = 무시
});

test("나중에 기록 — 저장·읽기, 깨진 값·저장소 실패는 기록 없음", () => {
  saveDismissed({ version: "v0.1.2", at: T });
  expect(JSON.parse(localStorage.getItem(DISMISS_KEY)!)).toEqual({ version: "v0.1.2", at: T });
  expect(readDismissed()).toEqual({ version: "v0.1.2", at: T });
  localStorage.setItem(DISMISS_KEY, "{깨짐");
  expect(readDismissed()).toBeNull();
  localStorage.setItem(DISMISS_KEY, JSON.stringify({ version: 1, at: "x" }));
  expect(readDismissed()).toBeNull();
  const get = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("denied"); });
  const set = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("denied"); });
  expect(readDismissed()).toBeNull();
  expect(() => saveDismissed({ version: "v0.1.2", at: T })).not.toThrow();
  get.mockRestore(); set.mockRestore();
});

test("최신 조회 — releases/latest 한 곳, 실패·오류 상태·형식 이상은 null", async () => {
  const f = vi.fn(async (_url: string, _init?: RequestInit) => new Response(JSON.stringify(OK), { status: 200 }));
  vi.stubGlobal("fetch", f);
  expect(await fetchLatest()).toEqual(REL);
  expect(f.mock.calls[0][0]).toBe(LATEST_URL);
  expect(LATEST_URL).toBe("https://api.github.com/repos/WJY-ador/personal-mycrm/releases/latest");
  vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 403 })));
  expect(await fetchLatest()).toBeNull();
  vi.stubGlobal("fetch", vi.fn(async () => new Response("not json", { status: 200 })));
  expect(await fetchLatest()).toBeNull();
  vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("Failed to fetch"); }));
  expect(await fetchLatest()).toBeNull();
});

const fn = () => Promise.resolve();
const API = { get: fn, onChange: () => () => {}, download: fn, install: fn };
const ST = { inApp: true, phase: "available", current: "0.2.0", version: "0.2.1", percent: null, reason: null };

test("다리 — 함수 넷이 다 있을 때만, 아니면 null(옛 길)", () => {
  expect(desktopBridge({ mycrmDesktop: { update: API } })).toBe(API);
  expect(desktopBridge({})).toBeNull();
  expect(desktopBridge(undefined)).toBeNull();
  expect(desktopBridge({ mycrmDesktop: {} })).toBeNull();
  expect(desktopBridge({ mycrmDesktop: { update: "x" } })).toBeNull();
  for (const k of ["get", "onChange", "download", "install"]) expect(desktopBridge({ mycrmDesktop: { update: { ...API, [k]: 1 } } })).toBeNull();
  const trap = { get mycrmDesktop() { throw new Error("denied"); } };
  expect(desktopBridge(trap)).toBeNull();
  expect(desktopBridge()).toBeNull();   // 시험 창(jsdom)에는 다리가 없다
});

test("앱 상태 검사 — 계약 모양만, 틀리면 null", () => {
  expect(parseState(ST)).toEqual(ST);
  expect(parseState({ ...ST, inApp: false })).toEqual({ ...ST, inApp: false });
  expect(parseState({ ...ST, phase: "idle", version: null })).toEqual({ ...ST, phase: "idle", version: null });
  expect(parseState({ ...ST, phase: "downloading", percent: 40 })).toEqual({ ...ST, phase: "downloading", percent: 40 });
  expect(parseState({ ...ST, phase: "downloading", percent: null })?.percent).toBeNull();          // 첫 진행 알림 전
  expect(parseState({ ...ST, phase: "available", percent: 40 })?.percent).toBeNull();              // downloading 밖의 percent 는 쓰지 않는다
  expect(parseState({ ...ST, phase: "error", reason: "install" })?.reason).toBe("install");
  expect(parseState({ ...ST, phase: "error", reason: null })?.reason).toBe("unknown");
  expect(parseState({ ...ST, phase: "available", reason: "network" })?.reason).toBeNull();
  const bad: unknown[] = [null, undefined, "x", 1, [], {},
    { ...ST, inApp: "true" }, { ...ST, phase: "done" }, { ...ST, current: "v0.2.0" }, { ...ST, current: "0.2" }, { ...ST, current: undefined },
    { ...ST, version: "v0.2.1" }, { ...ST, version: "0.2.1-beta" }, { ...ST, version: undefined },
    { ...ST, version: null }, { ...ST, version: "0.2.0" }, { ...ST, version: "0.1.9" },                 // available 인데 새 버전 없음·같음·낮음
    { ...ST, phase: "downloaded", version: null },
    { ...ST, percent: 40.5 }, { ...ST, percent: -1 }, { ...ST, percent: 101 }, { ...ST, percent: "40" }, { ...ST, percent: undefined },
    { ...ST, reason: "boom" }, { ...ST, reason: undefined },
    { ...ST, inApp: false, phase: "downloading" }, { ...ST, inApp: false, phase: "downloaded" }, { ...ST, inApp: false, phase: "error", version: null }];
  for (const b of bad) expect(parseState(b)).toBeNull();
});

test("릴리스 페이지 — 웹 상수로, 버전을 알면 태그 · 모르면 목록", () => {
  expect(releasePage("0.2.1")).toBe("https://github.com/WJY-ador/personal-mycrm/releases/tag/v0.2.1");
  expect(releasePage(null)).toBe("https://github.com/WJY-ador/personal-mycrm/releases");
  expect(releasePage("../x")).toBe("https://github.com/WJY-ador/personal-mycrm/releases");
});

test("앱 상태로 띄울지 — idle·checking 없음 · 나중에는 available·downloaded 만(v 붙은 옛 기록과 맞춘다) · downloading·error 는 늘", () => {
  const s = parseState(ST)!;
  expect(shouldShowApp(null, null, T)).toBe(false);
  expect(shouldShowApp({ ...s, phase: "idle" }, null, T)).toBe(false);
  expect(shouldShowApp({ ...s, phase: "checking" }, null, T)).toBe(false);
  expect(shouldShowApp(s, null, T)).toBe(true);
  const d = { version: "v0.2.1", at: T };
  expect(shouldShowApp(s, d, T + 1000)).toBe(false);
  expect(shouldShowApp(s, { version: "0.2.1", at: T }, T + 1000)).toBe(false);                   // v 없는 값도 같은 버전
  expect(shouldShowApp(s, d, T + SNOOZE_MS)).toBe(true);
  expect(shouldShowApp(s, { version: "v0.2.0", at: T }, T + 1000)).toBe(true);                   // 다른 버전 기록
  expect(shouldShowApp(s, { version: "v0.2.1", at: T + 5000 }, T)).toBe(true);                   // 미래 시각 기록 = 무시
  expect(shouldShowApp({ ...s, phase: "downloaded" }, d, T + 1000)).toBe(false);
  expect(shouldShowApp({ ...s, phase: "downloading", percent: 10 }, d, T + 1000)).toBe(true);
  expect(shouldShowApp({ ...s, phase: "error", reason: "network" }, d, T + 1000)).toBe(true);
});
