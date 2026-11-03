// 이름 관문·「표시 이름 바꾸기」(옛 test_web_home.py A5 정적 절을 옮김) — 안내 문구 · 빈 값만 화면이 막음 · POST /api/me/name · 성공 = 결과 한 줄(ctx.done) ·
// 서버 문구 그대로 · 다시 불러올 오류 = 문구 + reload · 관문의 [문의 보내기]는 관리자 아님만(서버 strip 과 같은 조건) · 대화창 = 열 때 지금 이름 · 저장하면 닫힘
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { SCREENS } from "../../layout/registry";
import { queryClient } from "../../shared/queries";
import type { AppState } from "../../shared/state";
import { calls, click, flush, installFetch, json, serve } from "../../test/fakeServer";
import { NAME_EMPTY, NAME_HELP, NAME_SAVED } from "./text";

const reload = vi.fn(async () => {}), done = vi.fn(async (_t: string) => {});
let el: HTMLDivElement, root: Root;
async function show(name: "name" | "namedlg", user: object, args: string[] = []) {
  const Screen = SCREENS[name];
  await act(async () => root.render(<QueryClientProvider client={queryClient}>
    <Screen ctx={{ reload, done, state: { user } as unknown as AppState, args }} /></QueryClientProvider>));
  await flush();
}
async function type(v: string) {
  const i = el.querySelector("input")!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(i, v);
    i.dispatchEvent(new Event("input", { bubbles: true }));
  });
}
const submit = () => click(el.querySelector('button[type="submit"]'));
const posts = () => calls.filter(c => c.method === "POST");
let reply = () => json(200, { ok: true });

beforeEach(() => {
  installFetch(); reload.mockClear(); done.mockClear();
  reply = () => json(200, { ok: true });
  serve(() => reply());
  HTMLDialogElement.prototype.showModal = function (this: HTMLDialogElement) { this.open = true; };
  HTMLDialogElement.prototype.close = function (this: HTMLDialogElement) { this.open = false; };
  el = document.createElement("div"); document.body.append(el); root = createRoot(el);
});
afterEach(() => { act(() => root.unmount()); el.remove(); vi.unstubAllGlobals(); });

test("관문 — 제목·안내·처리방침·[문의 보내기](관리자 아님)·[로그아웃] · 입력에 포커스", async () => {
  await show("name", { display_name: "", nav: "new" });
  expect(el.querySelector("h2")!.textContent).toBe("표시 이름을 정해 주세요");
  expect(el.textContent).toContain(NAME_HELP);
  expect(el.querySelector('a[href="/privacy"]')).not.toBeNull();
  expect([...el.querySelectorAll("[data-open]")].map(b => b.getAttribute("data-open"))).toEqual(["send", "logout"]);
  expect(document.activeElement).toBe(el.querySelector("#name-gate-input"));
  act(() => root.unmount()); root = createRoot(el);
  await show("name", { display_name: "", nav: "new", admin: true });
  expect([...el.querySelectorAll("[data-open]")].map(b => b.getAttribute("data-open"))).toEqual(["logout"]);
});

test("빈 값 = 화면 문구 · 요청 0 → 저장 = POST /api/me/name 1 · 결과 한 줄(ctx.done)", async () => {
  await show("name", { display_name: "", nav: "new" });
  await type("   ");
  await submit();
  expect(el.querySelector(".ferr")!.textContent).toBe(NAME_EMPTY);
  expect(posts().length).toBe(0);
  await type("홍길동");
  await submit();
  expect(posts()).toEqual([{ url: "/api/me/name", method: "POST", body: { display_name: "홍길동" } }]);
  expect(done).toHaveBeenCalledWith(NAME_SAVED);
  expect(el.querySelector(".ferr")!.textContent).toBe("");
});

test("실패 — 서버 문구 그대로 · 충돌 = 다시 불러옴 + 문구 · 연결 실패 문구", async () => {
  await show("name", { display_name: "", nav: "new" });
  reply = () => json(400, { code: "NAME-INVALID", msg: "표시 이름은 40자까지예요." });
  await type("홍길동"); await submit();
  expect(el.querySelector(".ferr")!.textContent).toBe("표시 이름은 40자까지예요.");
  expect(done).not.toHaveBeenCalled(); expect(reload).not.toHaveBeenCalled();
  reply = () => json(400, { code: "CONFLICT", msg: "x" });
  await submit();
  expect(el.querySelector(".ferr")!.textContent).toContain("다른 곳에서 먼저 바뀌었어요.");
  expect(reload).toHaveBeenCalledTimes(1);
  reply = () => { throw new TypeError("offline"); };
  await submit();
  expect(el.querySelector(".ferr")!.textContent).toBe("서버에 연결하지 못했어요. 잠시 뒤 다시 해 보세요.");
});

test("대화창 — 닫힌 채 자리만 · 열면 지금 이름·문구 비움 · 저장하면 닫힘 + 결과 한 줄 · [취소]·[닫기]", async () => {
  await show("namedlg", { display_name: "홍길동", nav: "new" });
  const dlg = el.querySelector("dialog")!;
  expect(dlg.open).toBe(false);
  await show("namedlg", { display_name: "홍길동", nav: "new" }, ["open"]);
  expect(dlg.open).toBe(true);
  expect((el.querySelector("#name-dlg-input") as HTMLInputElement).value).toBe("홍길동");
  await type(""); await submit();
  expect(el.querySelector(".ferr")!.textContent).toBe(NAME_EMPTY);
  await click([...el.querySelectorAll("button")].find(b => b.textContent === "취소"));
  expect(dlg.open).toBe(false);
  await show("namedlg", { display_name: "홍길동", nav: "new" }, ["open"]);   // 다시 열면 = 지금 이름 · 문구 비움
  expect(dlg.open).toBe(true);
  expect((el.querySelector("#name-dlg-input") as HTMLInputElement).value).toBe("홍길동");
  expect(el.querySelector(".ferr")!.textContent).toBe("");
  await type("새 이름"); await submit();
  expect(posts()[0].body).toEqual({ display_name: "새 이름" });
  expect(dlg.open).toBe(false);
  expect(done).toHaveBeenCalledWith(NAME_SAVED);
});
