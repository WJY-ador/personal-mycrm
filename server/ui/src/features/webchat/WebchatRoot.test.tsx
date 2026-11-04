// 웹 「대화」 화면 — 스위치 꺼짐 = 버튼·패널 0 · 켜짐 = 탭 줄 「AI 대화」 버튼 · 열면 패널(PC 상태·턴·도구 접힘·답·중지) · 남의 데이터 없음.
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import type { AppState } from "../../shared/state";
import { flush } from "../../test/fakeServer";
import { WebchatStore } from "./store";
import { WebchatRoot } from "./WebchatRoot";
import { PC_ON, TITLE } from "./text";

let el: HTMLDivElement, nav: HTMLSpanElement, root: Root;
beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  nav = document.createElement("span"); nav.id = "ui-chatnav";
  el = document.createElement("div");
  document.body.append(nav, el); root = createRoot(el);
});
afterEach(() => { act(() => root.unmount()); el.remove(); nav.remove(); });
const st = (webchat: boolean) => ({ user: { display_name: "홍길동", nav: "new" }, switches: { trash: false, webchat } }) as unknown as AppState;
const reload = vi.fn(async () => {});

function mk() {
  const s = new WebchatStore();
  const ls: Record<string, (e: MessageEvent) => void> = {};
  s.api = {
    open: vi.fn(async () => ({ session_id: "cs_1", status: "active", device_id: "is_1", connected: true })),
    turn: vi.fn(async () => ({ turn_id: "ct_1", status: "running", created: true })),
    stop: vi.fn(async () => ({ turn_id: "ct_1" })),
    stream: vi.fn(() => ({ onmessage: null, onerror: null, close() {}, addEventListener: (t: string, f: (e: MessageEvent) => void) => { ls[t] = f; } })),
  };
  const fire = (t: string, d: unknown) => act(() => ls[t]({ data: JSON.stringify(d) } as MessageEvent));
  return { s, fire };
}

test("스위치 꺼짐 = 버튼·패널 0", async () => {
  const { s } = mk();
  await act(async () => root.render(<WebchatRoot ctx={{ reload, state: st(false) }} store={s} />));
  expect(nav.childElementCount).toBe(0);
  expect(el.querySelector("aside#webchat")).toBeNull();
});

test("켜짐 = 버튼 → 패널 · PC 연결 · 턴(사용자 글·도구 접힘·답 굵게·중지) · 남의 데이터 없음", async () => {
  const { s, fire } = mk();
  await act(async () => root.render(<WebchatRoot ctx={{ reload, state: st(true) }} store={s} />));
  const a = nav.querySelector("a") as HTMLAnchorElement;
  expect(a.textContent).toBe(TITLE);
  const aside = () => el.querySelector("aside#webchat") as HTMLElement;
  expect(aside().hidden).toBe(true);
  await act(async () => { a.click(); }); await flush();
  expect(aside().hidden).toBe(false);
  expect(aside().querySelector("header [role=status]")?.textContent).toBe(PC_ON);
  fire("turn", { turn_id: "ct_1", text: "안녕", user_id: "u-other", email: "other@example.com" });
  fire("tool_call", { turn_id: "ct_1", seq: 1, data: { name: "find", input: { q: "x" } } });
  fire("delta", { turn_id: "ct_1", seq: 2, data: { text: "**중요** 답" } });
  const turn = aside().querySelector("[data-turn=ct_1]") as HTMLElement;
  expect(turn.querySelector("p")?.textContent).toBe("안녕");
  expect(turn.querySelector("details summary")?.textContent).toBe("도구 1번 사용");
  expect(turn.querySelector("strong")?.textContent).toBe("중요");
  expect(aside().textContent).not.toContain("other@example.com");
  const stop = [...aside().querySelectorAll("button")].find(b => b.textContent === "중지") as HTMLButtonElement;
  expect(stop).toBeTruthy();
  const send = [...aside().querySelectorAll("button")].find(b => b.textContent === "보내기") as HTMLButtonElement;
  expect(send.disabled).toBe(true);   // 실행 중 = 보내기 잠금
  await act(async () => { stop.click(); });
  expect(s.api.stop).toHaveBeenCalledWith("cs_1");
  fire("done", { turn_id: "ct_1", seq: 3, data: {} });
  expect([...aside().querySelectorAll("button")].some(b => b.textContent === "중지")).toBe(false);
});
