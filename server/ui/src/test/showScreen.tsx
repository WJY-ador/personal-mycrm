// 시험 도우미 — 옮긴 화면 하나를 레지스트리(SCREENS) 그대로 띄운다(R4 이관·연결 장치·활동). 주소는 history 로만(껍데기 라우터 없음) —
// 같은 자리에 다시 그리면 껍데기 uiMount 와 같다(같은 화면 = 자리 유지, args 만 바뀜).
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClientProvider } from "@tanstack/react-query";
import { vi } from "vitest";
import { SCREENS } from "../layout/registry";
import { queryClient } from "../shared/queries";
import type { AppState } from "../shared/state";
import { flush } from "./fakeServer";

export const reload = vi.fn(async () => {});
let el: HTMLDivElement | null = null, root: Root | null = null;

export async function showScreen(name: string, hash: string, args: string[], state: object = {}) {
  history.replaceState(null, "", hash);
  if (!el) { el = document.createElement("div"); document.body.append(el); root = createRoot(el); }
  const Screen = SCREENS[name];
  await act(async () => root!.render(<QueryClientProvider client={queryClient}><Screen ctx={{ reload, state: state as AppState, args }} /></QueryClientProvider>));
  await flush();
  await flush();
  return el;
}

export function hideScreen() {
  if (root) act(() => root!.unmount());
  el?.remove();
  el = root = null;
}

export const byText = (e: Element, sel: string, t: string) => [...e.querySelectorAll(sel)].filter(b => b.textContent === t);
export const cacheText = () => JSON.stringify(queryClient.getQueryCache().getAll().map(q => q.state.data));
