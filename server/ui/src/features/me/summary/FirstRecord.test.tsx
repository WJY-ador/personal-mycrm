// 첫 기록 카드 [복사] — 성공 = 그 자리에 "복사했어요", 거절이나 지원 안 함 = 직접 골라 복사하라는 한 줄. 결과 자리(role=status)는 처음부터 있다
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { click } from "../../../test/fakeServer";
import { COPY_FAIL, COPY_OK, FIRST_SAY, FirstRecord } from "./FirstRecord";

let el: HTMLDivElement, root: Root;
const had = Object.getOwnPropertyDescriptor(navigator, "clipboard");
const setClip = (v: unknown) => Object.defineProperty(navigator, "clipboard", { value: v, configurable: true });

beforeEach(async () => {
  el = document.createElement("div");
  document.body.append(el);
  root = createRoot(el);
});
afterEach(() => {
  act(() => root.unmount());
  el.remove();
  if (had) Object.defineProperty(navigator, "clipboard", had); else delete (navigator as { clipboard?: unknown }).clipboard;
});
const show = async () => { await act(async () => root.render(<FirstRecord />)); };
const btn = (label: string) => el.querySelector(`button[aria-label='${label}']`);
const says = () => [...el.querySelectorAll("[role=status]")].map(s => s.textContent);

test("복사 성공 — 누른 줄에만 복사했어요, 복사한 값 = 화면 글자 그대로", async () => {
  const writeText = vi.fn(async () => {});
  setClip({ writeText });
  await show();
  expect(says()).toEqual(["", ""]);
  await click(btn("MCP 주소 복사"));
  expect(writeText).toHaveBeenLastCalledWith(location.origin + "/mcp");
  expect(says()).toEqual([COPY_OK, ""]);
  await click(btn("첫 마디 복사"));
  expect(writeText).toHaveBeenLastCalledWith(FIRST_SAY);
  expect(says()).toEqual([COPY_OK, COPY_OK]);
});

test("복사 거절 — 직접 골라 복사하라는 한 줄, 글자는 화면에 그대로", async () => {
  setClip({ writeText: vi.fn(async () => { throw new Error("denied"); }) });
  await show();
  await click(btn("첫 마디 복사"));
  expect(says()).toEqual(["", COPY_FAIL]);
  expect(el.querySelector("#first-record-say")!.textContent).toBe(FIRST_SAY);
});

test("클립보드 없음 — 같은 안내 한 줄", async () => {
  setClip(undefined);
  await show();
  await click(btn("MCP 주소 복사"));
  expect(says()).toEqual([COPY_FAIL, ""]);
  expect(el.querySelector("#first-record-mcp")!.textContent).toBe(location.origin + "/mcp");
});
