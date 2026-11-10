// 기다림 캐릭터 — 낭독기에는 글자 하나(role=status + 숨긴 글자) · 이름 없으면 장식(aria-hidden) · 인라인 SVG(이미지 파일 0) · 움직임 줄이기 = 멈춤 · 색은 토큰만
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, test } from "vitest";
import { Sprout } from "./Sprout";

type Fs = { readFileSync(f: string, e: "utf-8"): string };
const proc = (globalThis as unknown as { process: { getBuiltinModule(n: string): Fs; cwd(): string } }).process;
const CSS = proc.getBuiltinModule("node:fs").readFileSync(`${proc.cwd()}/src/shared/Sprout.module.css`, "utf-8");

function draw(node: React.ReactNode) {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  const el = document.createElement("div");
  document.body.append(el);
  const root = createRoot(el);
  act(() => root.render(node));
  return { el, done: () => { act(() => root.unmount()); el.remove(); } };
}

test("이름 있음 = role=status 하나 + 글자 하나(숨김 또는 보임) · SVG 는 aria-hidden", () => {
  const { el, done } = draw(<Sprout label="답을 기다리는 중" />);
  const st = el.querySelectorAll("[role=status]");
  expect(st.length).toBe(1);
  expect(st[0].textContent).toBe("답을 기다리는 중");
  expect(st[0].querySelector(".sr")?.textContent).toBe("답을 기다리는 중");
  expect(el.querySelector("svg")?.getAttribute("aria-hidden")).toBe("true");
  expect(el.querySelector("img")).toBeNull();
  done();
  const v = draw(<Sprout label="허용 대기" visible />);
  expect(v.el.querySelector("[role=status] .sr")).toBeNull();
  expect(v.el.textContent).toBe("허용 대기");
  v.done();
});

test("이름 없음 = 장식(낭독기가 읽지 않는다)", () => {
  const { el, done } = draw(<Sprout />);
  expect(el.querySelector("[role=status]")).toBeNull();
  expect(el.firstElementChild?.getAttribute("aria-hidden")).toBe("true");
  expect(el.textContent).toBe("");
  done();
});

test("움직임 줄이기 = 애니메이션 없음 · 색은 var(--…) 토큰만", () => {
  expect(CSS).toMatch(/@media \(prefers-reduced-motion: reduce\) \{ \.leaf \{ animation: none; \} \}/);
  expect(CSS).toMatch(/\.leaf \{[^}]*animation: sway/);
  const colors = [...CSS.matchAll(/(?:fill|stroke|color|background):\s*([^;]+);/g)].map(m => m[1].trim());
  expect(colors.length).toBeGreaterThan(3);
  expect(colors.filter(c => !/^var\(--[\w-]+\)$/.test(c) && c !== "none")).toEqual([]);
  expect(CSS).not.toMatch(/#[0-9a-fA-F]{3,8}\b|rgb\(|url\(/);
});
