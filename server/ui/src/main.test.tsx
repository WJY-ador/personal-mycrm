// 공존 다리 — 같은 자리 다시 mount = 화면 상태 유지 · crm:state = 다시 받기 · 떠나면 unmount · 모듈보다 먼저 맡긴 자리.
import { act } from "react";
import { beforeAll, beforeEach, expect, test, vi } from "vitest";
import { queryClient } from "./shared/queries";
import { calls, click, flush, installFetch, json, serve } from "./test/fakeServer";

const ROW = { kind: "record", id: "r1", title: "글", trashed_at: "2026-10-23T01:00:00Z", purge_at: "2026-10-30T01:00:00Z", revision: null, restore_state: null };
const ctx = { reload: vi.fn(async () => {}) };
let pendingEl: HTMLDivElement;

beforeAll(async () => {
  installFetch();
  serve(() => json(200, { items: [ROW], next_cursor: "", hours: 168 }));
  pendingEl = document.createElement("div");
  document.body.append(pendingEl);
  window.CrmUIPending = ["trash", pendingEl, ctx];   // 옛 라우터가 모듈보다 먼저 자리를 맡겼다
  await act(async () => { await import("./main"); });
  await flush();
});
beforeEach(() => { calls.length = 0; });

test("맡겨 둔 자리 = 모듈이 뜨면 띄운다 · 다리는 mount·unmount 둘", () => {
  expect(Object.keys(window.CrmUI!).sort()).toEqual(["mount", "unmount"]);
  expect(window.CrmUIPending).toBeUndefined();
  expect(pendingEl.textContent).toContain("휴지통");
  act(() => window.CrmUI!.unmount("trash"));
  expect(pendingEl.textContent).toBe("");
});

test("같은 자리 다시 mount = 문구 유지 · crm:state = 목록 다시 받기 · unmount = 비움", async () => {
  const el = document.createElement("div");
  document.body.append(el);
  queryClient.clear();
  await act(async () => window.CrmUI!.mount("trash", el, ctx));
  await flush();
  serve((_u, m) => json(200, m === "POST" ? {} : { items: [ROW], next_cursor: "", hours: 168 }));
  await click([...el.querySelectorAll("button")].find(b => b.textContent === "복원"));
  expect(el.querySelector("#trash-msg")!.textContent).toBe("복원했어요.");
  await act(async () => window.CrmUI!.mount("trash", el, ctx));   // 옛 render() 가 상태를 받아 다시 그림
  await flush();
  expect(el.querySelector("#trash-msg")!.textContent).toBe("복원했어요.");
  calls.length = 0;
  await act(async () => { window.dispatchEvent(new Event("crm:state")); });
  await flush();
  expect(calls.map(c => c.url)).toEqual(["/api/trash"]);
  act(() => window.CrmUI!.unmount("trash"));
  expect(el.textContent).toBe("");
  expect(() => window.CrmUI!.mount("nope", el, ctx)).toThrow();
});
