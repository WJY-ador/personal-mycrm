// Setup 「휴지통」(옛 test_web_home.py test_trash_flow 의 Setup 절을 옮김) — 행·빈 상태·안내·더 보기·복원·영구 삭제·기한 이후·불러오기 실패.
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { queryClient } from "../../shared/queries";
import { calls, click, flush, installFetch, json, serve, text } from "../../test/fakeServer";
import { TrashScreen } from "./TrashScreen";
import { TRASH_NOTE, TRASH_PURGE_ASK, TRASH_PURGED } from "./text";

const ROWS = [
  { kind: "record", id: "r1", title: "<첫 글>", trashed_at: "2026-10-23T01:00:00Z", purge_at: "2026-10-30T01:00:00Z", revision: null, restore_state: null },
  { kind: "person", id: "p1", title: "민수", trashed_at: "2026-10-22T15:30:00Z", purge_at: "2026-10-29T15:30:00Z", revision: 2, restore_state: null },
];
const MORE = [{ kind: "item", id: "i9", title: "결정 하나", object_label: "결정", trashed_at: "2026-10-21T00:00:00Z", purge_at: "2026-10-28T00:00:00Z", revision: 1, restore_state: "pending" }];
let el: HTMLDivElement, root: Root;
const reload = vi.fn(async () => {});

async function show() {
  el = document.createElement("div");
  document.body.append(el);
  root = createRoot(el);
  await act(async () => root.render(<QueryClientProvider client={queryClient}><TrashScreen ctx={{ reload }} /></QueryClientProvider>));
  await flush();
}
const msg = () => el.querySelector("#trash-msg")!;
const btn = (label: string, i = 0) => [...el.querySelectorAll("button")].filter(b => b.textContent === label)[i];

beforeEach(() => {
  installFetch();
  queryClient.clear();
  reload.mockClear();
  serve(url => json(200, url.includes("cursor=c2") ? { items: MORE, next_cursor: "", hours: 168 } : { items: ROWS, next_cursor: "c2", hours: 168 }));
});
afterEach(() => { act(() => root.unmount()); el.remove(); vi.unstubAllGlobals(); });

test("빈 상태 = 안내 + 「휴지통이 비어 있어요.」 · 버튼 0", async () => {
  serve(() => json(200, { items: [], next_cursor: "", hours: 168 }));
  await show();
  expect(el.textContent).toContain(TRASH_NOTE);
  expect(text(el, ".empty")).toEqual(["휴지통이 비어 있어요."]);
  expect(el.querySelectorAll("button").length).toBe(0);
});

test("행 = 종류 · 제목(글자 그대로) · 삭제 시각 · 복원 가능 기한(사용자 시간대) · [더 보기] 1", async () => {
  await show();
  expect(calls.map(c => c.url)).toEqual(["/api/trash"]);
  expect(el.querySelectorAll("li").length).toBe(2);
  expect(text(el, ".chip")).toEqual(["내 글", "사람"]);
  expect(text(el, "li b")).toEqual(["<첫 글>", "민수"]);
  expect(el.querySelector("li b")!.children.length).toBe(0);   // 제목은 글자로만(요소가 생기지 않는다)
  expect(text(el, ".recmeta")).toEqual(["10월 23일 10:00 삭제 · 복원 가능 기한 10월 30일 10:00", "10월 23일 00:30 삭제 · 복원 가능 기한 10월 30일 00:30"]);
  expect(text(el, "button")).toEqual(["복원", "영구 삭제", "복원", "영구 삭제", "더 보기"]);
  expect(el.textContent).not.toMatch(/처리 중|영구 삭제 예정/);
});

test("백그라운드 재조회 실패 = 기존 휴지통 목록 유지 + 오류 안내", async () => {
  await show();
  serve(() => json(503, { code: "OFFLINE", msg: "" }));
  await act(async () => { await queryClient.invalidateQueries({ queryKey: ["trash"] }); });
  await flush();
  expect(el.querySelectorAll("li")).toHaveLength(2);
  expect(el.querySelector('[role="alert"]')?.textContent).toBe("서버에 연결하지 못했어요.");
});

test("[더 보기] = 서버 커서 그대로 · 항목 종류 = object_label · 끝이면 버튼 0", async () => {
  await show();
  await click(btn("더 보기"));
  expect(calls.at(-1)?.url).toBe("/api/trash?cursor=c2");
  expect(text(el, ".chip")).toEqual(["내 글", "사람", "결정"]);
  expect(btn("더 보기")).toBeUndefined();
});

test("[더 보기] 실패 = 문구 · 목록 유지", async () => {
  await show();
  serve(() => json(500, {}));
  await click(btn("더 보기"));
  expect(msg().textContent).toBe("더 불러오지 못했어요. 다시 눌러 주세요.");
  expect(msg().className).toBe("ferr");
  expect(el.querySelectorAll("li").length).toBe(2);
});

test("[복원] = 종류·ID 로 요청 → 「복원했어요.」 → 상태 다시 받기", async () => {
  await show();
  await click(btn("복원"));
  expect(calls.at(-1)).toEqual({ url: "/api/trash/restore", method: "POST", body: { kind: "record", id: "r1" } });
  expect(reload).toHaveBeenCalledTimes(1);
  expect(msg().textContent).toBe("복원했어요.");
  expect(msg().className).toBe("fok");
});

test("[영구 삭제] = 확인창(r4 문구) · 취소 = 요청 0 · 확인 = 요청 + 접수 문구", async () => {
  await show();
  const ask = vi.fn(() => false);
  vi.stubGlobal("confirm", ask);
  const n = calls.length;
  await click(btn("영구 삭제", 1));
  expect(calls.length).toBe(n);
  expect(ask).toHaveBeenCalledWith(TRASH_PURGE_ASK);
  ask.mockReturnValue(true);
  await click(btn("영구 삭제", 1));
  expect(calls.at(-1)).toEqual({ url: "/api/trash/purge", method: "POST", body: { kind: "person", id: "p1" } });
  expect(msg().textContent).toBe(TRASH_PURGED);
});

test("기한 이후 = 「복원 기간이 끝났어요.」(ferr) · 그래도 상태 다시 받기", async () => {
  await show();
  serve((_u, m) => (m === "POST" ? json(400, { code: "TRASH-EXPIRED", msg: "서버 문구" }) : json(200, { items: ROWS, next_cursor: "", hours: 168 })));
  await click(btn("복원"));
  expect(msg().textContent).toBe("복원 기간이 끝났어요.");
  expect(msg().className).toBe("ferr");
  expect(reload).toHaveBeenCalledTimes(1);
});

test("불러오기 실패 — 연결 끊김 = 「서버에 연결하지 못했어요.」 · 그 밖 = 새로 고침 안내", async () => {
  serve(() => { throw new TypeError("network"); });
  await show();
  expect(text(el, ".empty")).toEqual(["서버에 연결하지 못했어요."]);
  act(() => root.unmount());
  queryClient.clear();
  serve(() => json(500, { code: "X" }));
  await show();
  expect(text(el, ".empty")).toEqual(["휴지통을 불러오지 못했어요. 새로 고침해 주세요."]);
});
