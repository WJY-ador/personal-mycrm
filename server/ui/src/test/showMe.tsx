// 시험 도우미 — 「나」 화면을 레지스트리(SCREENS.me — 블록·기본 배치 포함) 그대로 띄운다. 주소는 history 로만 바꾼다(껍데기 라우터 없음).
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClientProvider } from "@tanstack/react-query";
import { vi } from "vitest";
import { SCREENS } from "./screens";
import { queryClient } from "../shared/queries";
import type { AppState } from "../shared/state";
import { flush } from "./fakeServer";

export const reload = vi.fn(async () => {});
export const setDirty = vi.fn();
let el: HTMLDivElement | null = null, root: Root | null = null;

export async function showMe(hash: string, state: object, flash: { text: string } | null = null) {
  history.replaceState(null, "", hash);
  const [, a = "", b = ""] = hash.replace(/^#/, "").split("/");
  if (!el) { el = document.createElement("div"); document.body.append(el); root = createRoot(el); }
  const Me = SCREENS.me;
  await act(async () => root!.render(<QueryClientProvider client={queryClient}>
    <Me ctx={{ reload, setDirty, state: state as AppState, args: [a, b], flash }} />
  </QueryClientProvider>));
  await flush();
  await flush();
  return el;
}

export function hideMe() {
  if (root) act(() => root!.unmount());
  el?.remove();
  el = root = null;
}

export const btn = (e: Element, label: string) => [...e.querySelectorAll("button")].find(b => b.textContent === label);
export const btns = (e: Element) => [...e.querySelectorAll(".hacts button")].map(b => b.textContent);
export async function type(input: HTMLInputElement | HTMLTextAreaElement, v: string) {
  const set = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(input), "value")!.set!;
  await act(async () => { set.call(input, v); input.dispatchEvent(new Event("input", { bubbles: true })); });
}
