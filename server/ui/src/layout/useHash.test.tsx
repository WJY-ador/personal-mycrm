// 라우터 hash 구독 — AI 패널 표지(#_ai)는 화면 주소가 아니다: 그 hashchange 는 알리지 않고(미저장 보호, 맨 위로도 안 함), 그 동안은 마지막 화면 주소를 돌려준다
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { useHash } from "./useHash";

let el: HTMLDivElement, root: Root;
const seen: string[] = [];
const guard = vi.fn(() => false);
function Probe() { seen.push(useHash(guard)); return null; }
beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  el = document.createElement("div"); document.body.append(el); root = createRoot(el);
  seen.length = 0; guard.mockClear();
});
afterEach(() => { act(() => root.unmount()); el.remove(); history.replaceState(null, "", location.pathname); });

const fire = async (hash: string, from: string) => {
  const base = location.href.split("#")[0];
  history.replaceState(null, "", hash);
  await act(async () => { window.dispatchEvent(new HashChangeEvent("hashchange", { oldURL: base + from, newURL: base + hash })); });
};

test("#_ai 는 라우팅 대상이 아니다, 다른 hash 는 그대로 알린다", async () => {
  history.replaceState(null, "", location.pathname + "#records");
  await act(async () => root.render(<Probe />));
  expect(seen.at(-1)).toBe("#records");
  await fire("#_ai", "#records");
  expect(guard).not.toHaveBeenCalled();
  expect(seen.at(-1)).toBe("#records");
  history.replaceState(null, "", "#records");   // 웹 대화 섬이 표지를 지우고 앞 주소로 되돌린 뒤 늦게 도는 리스너도 같은 사건이면 무시
  await act(async () => { window.dispatchEvent(new HashChangeEvent("hashchange", { oldURL: location.href, newURL: location.href.split("#")[0] + "#_ai" })); });
  expect(guard).not.toHaveBeenCalled();
  await fire("#people", "#records");
  expect(guard).toHaveBeenCalledTimes(1);
  expect(seen.at(-1)).toBe("#people");
});
