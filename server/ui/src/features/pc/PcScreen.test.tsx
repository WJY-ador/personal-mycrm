// 설정 「이 PC」(2026-11-13 앱 하나) — 다리 없음 = 안내와 내려받기 · 다리 있음 = 상태 한 줄과 [지금 동기화] · 실패 이유 · 틀린 값 = 읽지 못함
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, expect, test } from "vitest";
import { flush } from "../../test/fakeServer";
import { PcScreen } from "./PcScreen";
import { BAD, NO_APP, SYNC } from "./text";

let el: HTMLDivElement, root: Root;
type W = { mycrmDesktop?: unknown };
afterEach(() => { act(() => root.unmount()); el.remove(); delete (window as unknown as W).mycrmDesktop; });

async function show() {
  el = document.createElement("div");
  document.body.append(el);
  root = createRoot(el);
  await act(async () => root.render(<PcScreen ctx={{ reload: async () => {} }} />));
  await flush();
}
function bridge(value: unknown, calls: string[] = []) {
  let push: (v: unknown) => void = () => {};
  (window as unknown as W).mycrmDesktop = { pc: { get: async () => value, onChange: (cb: (v: unknown) => void) => { push = cb; return () => {}; },
    sync: async () => { calls.push("sync"); } } };
  return (v: unknown) => push(v);
}
const base = { signed_in: true, device_id: "is_1", state: "ok", last_sync_at: "2026-11-13T05:02:00Z", last_result: "ok", last_code: null, app_version: "0.1.7" };

test("다리 없음(브라우저, 옛 앱) = 안내와 내려받기 링크, 장치 목록과 토큰 없음", async () => {
  await show();
  expect(el.textContent).toContain(NO_APP);
  expect(el.querySelector("a")?.getAttribute("href")).toBe("/download");
  expect(el.querySelector("input, textarea")).toBeNull();   // 토큰 칸, 장치 이름 칸 없음
  expect(el.querySelector("button")).toBeNull();
});

test("다리 있음 = 상태 한 줄 + [지금 동기화], 누르면 다리 sync, 바뀐 상태는 onChange 로", async () => {
  const calls: string[] = [];
  const push = bridge(base, calls);
  await show();
  const row = el.querySelector("[aria-label='이 PC']") as HTMLElement;
  expect(row.textContent).toContain("연결됨");
  expect(row.textContent).toContain("성공");
  const b = [...el.querySelectorAll("button")].find(x => x.textContent === SYNC)!;
  await act(async () => { b.click(); }); await flush();
  expect(calls).toEqual(["sync"]);
  await act(async () => { push({ ...base, state: "failed", last_result: "failed", last_code: "HTTP-503" }); }); await flush();
  expect(row.textContent).toContain("마지막 동기화 실패");
  expect(row.textContent).toContain("서버가 거절했어요(HTTP-503)");
  await act(async () => { push({ ...base, state: "syncing" }); }); await flush();
  expect(([...el.querySelectorAll("button")].find(x => x.textContent === SYNC) as HTMLButtonElement).disabled).toBe(true);
  await act(async () => { push({ ...base, state: "login", signed_in: false, last_code: null }); }); await flush();
  expect(row.textContent).toContain("로그인이 끊겼어요");
});

test("틀린 값(경로가 섞인 코드, 모르는 상태) = 읽지 못함", async () => {
  bridge({ ...base, last_code: "C:/Users/me" });
  await show();
  expect(el.textContent).toContain(BAD);
});
