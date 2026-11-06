// 저장 승인 대기 하나 — 다시 받기 실패 = 받아 둔 글 그대로 + 못 읽음 안내 · 받아 둔 것이 없으면 = 처음 못 읽음 그대로(가짜 서버만)
import { act } from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { queryClient } from "../../shared/queries";
import { flush, installFetch, json, serve } from "../../test/fakeServer";
import { installMedia } from "../../test/meFixture";
import { hideScreen, reload, showScreen } from "../../test/showScreen";
import sample from "./today.sample.json";

const S = { user: { nav: "new" }, switches: { trash: true }, activity_ui: { actions: { like: "좋아요" }, providers: {}, pending_days: 30 }, inbox: { pending: 0 }, journal: [] };
const show = () => showScreen("today", "#_today/inbox/ie_s1", ["today", "inbox", "ie_s1"], S);
const KEY = ["inbox", "one", "ie_s1"];
const fail = (el: Element) => [...el.querySelectorAll('[role="alert"].partfail')].map(x => x.textContent).join(" ");

beforeEach(() => {
  installFetch(); installMedia(false); queryClient.clear(); reload.mockClear();
  serve(url => {
    if (url.startsWith("/api/inbox/")) return json(200, sample.one);
    if (url.startsWith("/api/inbox?")) return json(200, { entries: [], next_cursor: "", counts: { pending: 0 } });
    if (url.startsWith("/api/activities")) return json(200, { activities: [], next_cursor: "" });
    return json(404, {});
  });
});
afterEach(() => { hideScreen(); vi.unstubAllGlobals(); });

test("다시 받기 실패 = 받아 둔 대기 글(제목·승인 문구) 그대로 + 못 읽음 안내 · 처음부터 실패 = 못 읽음만", async () => {
  const el = await show();
  const title = el.querySelector("h2.title")!.textContent;
  expect(el.textContent).toContain(sample.one.approve_notice!);
  expect(fail(el)).toBe("");
  serve(() => json(503, { code: "OFFLINE", msg: "" }));
  await act(async () => { await queryClient.invalidateQueries({ queryKey: KEY, exact: true }); });
  await flush();
  expect(queryClient.getQueryState(KEY)?.status).toBe("error");
  expect(el.querySelector("h2.title")!.textContent).toBe(title);
  expect(el.textContent).toContain(sample.one.approve_notice!);
  expect(fail(el)).toContain("저장 승인 대기 글을 불러오지 못했어요");
  hideScreen(); queryClient.clear();
  const cold = await show();
  expect(fail(cold)).toContain("저장 승인 대기 글을 불러오지 못했어요");
  expect(cold.textContent).not.toContain(sample.one.approve_notice!);
});
