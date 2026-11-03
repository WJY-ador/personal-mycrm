// 시험 도우미 — 가짜 서버(fetch)와 React 렌더 흐름 맞추기. 화면 코드가 아니다(arch 규약 밖: *.test 만 import).
import { act } from "react";
import { vi } from "vitest";

export type Call = { url: string; method: string; body?: unknown };
export const calls: Call[] = [];
let reply: (url: string, method: string) => Response | Promise<Response> = () => json(500, {});

export const json = (status: number, j: unknown) =>
  new Response(JSON.stringify(j), { status, headers: { "content-type": "application/json" } });

export function serve(fn: typeof reply) {
  reply = fn;
}

export function installFetch() {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  calls.length = 0;
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method || "GET";
    calls.push({ url, method, body: init?.body ? JSON.parse(String(init.body)) : undefined });
    return reply(url, method);
  }));
}

export const flush = () => act(async () => { await new Promise(r => setTimeout(r, 0)); });

export const text = (el: Element, sel: string) => [...el.querySelectorAll(sel)].map(x => x.textContent);

export async function click(el: Element | null | undefined) {
  if (!el) throw new Error("누를 버튼이 없어요");
  await act(async () => { (el as HTMLElement).click(); });
  await flush();
}
