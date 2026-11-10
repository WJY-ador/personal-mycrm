// PC 앱 새 버전 띠 판정 — 순수 함수(UA·버전 비교·릴리스 응답 검사·나중에 24시간) + 조회 실패 = null. 실제 네트워크는 부르지 않는다.
import { afterEach, expect, test, vi } from "vitest";
import { DISMISS_KEY, LATEST_URL, SNOOZE_MS, fetchLatest, installedVersion, newer, parseRelease, readDismissed, saveDismissed,
  shouldShow } from "./desktopUpdate";

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
