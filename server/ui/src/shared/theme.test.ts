// 화면 테마(server/assets/theme.js, 결정 5) — 고른 값(crm-theme)이 있으면 그것, 없으면 OS 다크 설정. 첫 그리기 전(스크립트 실행 즉시) 정해지고,
// 고른 값이 없을 때만 OS 변경을 따라간다. 토글은 반대로 바꾸고 고른 값을 저장한다. 스크립트를 jsdom 에서 그대로 돌린다.
import { afterEach, expect, test, vi } from "vitest";
import src from "../../../assets/theme.js?raw";

type L = (e: unknown) => void;
const added: [EventTarget, string, EventListener][] = [];
let osListeners: L[] = [];

function run(osDark: boolean, saved?: string) {
  if (saved) localStorage.setItem("crm-theme", saved);
  const mq = { matches: osDark, media: "(prefers-color-scheme: dark)", addEventListener: (_: string, f: L) => osListeners.push(f), removeEventListener() {} };
  vi.stubGlobal("matchMedia", (q: string) => (q === mq.media ? mq : { matches: false, addEventListener() {}, removeEventListener() {} }));
  for (const t of [document, window] as EventTarget[]) {
    const orig = t.addEventListener.bind(t);
    vi.spyOn(t, "addEventListener").mockImplementation((type: string, f: EventListenerOrEventListenerObject | null) => {
      added.push([t, type, f as EventListener]);
      orig(type, f);
    });
  }
  new Function(src)();
  vi.restoreAllMocks();
  return { setOs(dark: boolean) { mq.matches = dark; osListeners.forEach(f => f({ matches: dark })); } };
}
const theme = () => document.documentElement.getAttribute("data-theme");

afterEach(() => {
  for (const [t, type, f] of added.splice(0)) t.removeEventListener(type, f);
  osListeners = [];
  vi.unstubAllGlobals();
  localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
  document.body.replaceChildren();
});

test("고른 값 없음 — OS 다크면 실행 즉시 어둠, OS 밝음이면 밝음", () => {
  run(true);
  expect(theme()).toBe("dark");
  for (const [t, type, f] of added.splice(0)) t.removeEventListener(type, f);
  document.documentElement.removeAttribute("data-theme");
  run(false);
  expect(theme()).toBeNull();
});

test("고른 값이 OS 를 덮는다 — light + OS 다크 = 밝음, dark + OS 밝음 = 어둠", () => {
  run(true, "light");
  expect(theme()).toBeNull();
  for (const [t, type, f] of added.splice(0)) t.removeEventListener(type, f);
  localStorage.clear();
  run(false, "dark");
  expect(theme()).toBe("dark");
});

test("모르는 저장값은 고른 값이 아니다 — OS 를 따른다", () => {
  run(true, "sepia");
  expect(theme()).toBe("dark");
});

test("OS 변경 — 고른 값이 없을 때만 따라간다", () => {
  const a = run(false);
  expect(theme()).toBeNull();
  a.setOs(true);
  expect(theme()).toBe("dark");
  a.setOs(false);
  expect(theme()).toBeNull();
  localStorage.setItem("crm-theme", "light");
  a.setOs(true);
  expect(theme()).toBeNull();
});

test("토글 — 반대로 바꾸고 저장, 버튼 글자·누름 상태를 맞춘다", () => {
  const b = document.createElement("button");
  b.setAttribute("data-theme-toggle", "");
  b.hidden = true;
  document.body.append(b);
  run(true);
  expect(theme()).toBe("dark");
  expect(b.hidden).toBe(false);
  expect(b.getAttribute("aria-pressed")).toBe("true");
  b.click();
  expect(theme()).toBeNull();
  expect(localStorage.getItem("crm-theme")).toBe("light");
  expect(b.getAttribute("aria-pressed")).toBe("false");
  b.click();
  expect(theme()).toBe("dark");
  expect(localStorage.getItem("crm-theme")).toBe("dark");
});

test("다른 탭에서 지우면 OS 로 돌아간다", () => {
  run(true, "light");
  expect(theme()).toBeNull();
  localStorage.removeItem("crm-theme");
  window.dispatchEvent(new StorageEvent("storage", { key: "crm-theme", newValue: null }));
  expect(theme()).toBe("dark");
});
