// 활동 하나·축 하나 — 다시 받기 실패 = 받아 둔 화면 그대로 + 못 읽음 안내 · 받아 둔 것이 없으면 = 처음 못 읽음 그대로(가짜 서버만)
import { act } from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { queryClient } from "../../shared/queries";
import { flush, installFetch, json, serve } from "../../test/fakeServer";
import { hideScreen, reload, showScreen } from "../../test/showScreen";
import sample from "./activity.sample.json";

const S = {
  user: { nav: "new" }, switches: { trash: true }, activity_ui: { actions: { like: "좋아요", comment: "댓글" }, providers: { sns: "SNS" }, pending_days: 30 },
  activity: { ...sample.agg, period: "30d" }, people: [{ id: "p_p1", alias: "사람-P1" }], sources: [], items: [], definitions: [],
};
const show = (hash: string, args: string[]) => showScreen("activity", hash, args, S);
const OFF = () => json(503, { code: "OFFLINE", msg: "" });
const alert = (el: Element) => el.querySelector('[role="alert"].partfail')?.textContent || "";

beforeEach(() => {
  installFetch(); queryClient.clear(); reload.mockClear();
  serve(url => {
    if (url.startsWith("/api/activities/")) return json(200, sample.one);
    if (url.startsWith("/api/axes/")) return json(200, sample.axis);
    return json(404, {});
  });
});
afterEach(() => { hideScreen(); vi.unstubAllGlobals(); });

test("활동 하나 — 다시 받기 실패 = 받아 둔 활동 그대로 + 못 읽음 안내 · 처음부터 실패 = 못 읽음만", async () => {
  const el = await show("#_obj/activity/a_a2", ["activity", "a_a2", ""]);
  const title = el.querySelector("h2.title")!.textContent;
  expect(title).toBeTruthy();
  expect(alert(el)).toBe("");
  serve(OFF);
  await act(async () => { await queryClient.invalidateQueries({ queryKey: ["activity", "one", "a_a2"] }); });
  await flush();
  expect(queryClient.getQueryState(["activity", "one", "a_a2"])?.status).toBe("error");
  expect(el.querySelector("h2.title")!.textContent).toBe(title);
  expect(el.querySelector('a[href="#_me/journal/r_sample"]')).not.toBeNull();
  expect(alert(el)).toContain("활동을 불러오지 못했어요");
  hideScreen(); queryClient.clear();
  const cold = await show("#_obj/activity/a_a2", ["activity", "a_a2", ""]);
  expect(alert(cold)).toContain("활동을 불러오지 못했어요");
  expect(cold.querySelector("h2.title")).toBeNull();
});

test("축 하나 — 다시 받기 실패 = 받아 둔 축 그대로 + 못 읽음 안내 · 처음부터 실패 = 못 읽음만", async () => {
  const el = await show("#_obj/axis/i_x1", ["axis", "i_x1", ""]);
  expect(el.querySelector("h2.title")!.textContent).toBe("축 X1");
  serve(OFF);
  await act(async () => { await queryClient.invalidateQueries({ queryKey: ["activity", "axis", "i_x1"] }); });
  await flush();
  expect(queryClient.getQueryState(["activity", "axis", "i_x1"])?.status).toBe("error");
  expect(el.querySelector("h2.title")!.textContent).toBe("축 X1");
  expect(el.querySelector('a[href="#structure/od_principles/i_sample"]')).not.toBeNull();
  expect(alert(el)).toContain("축을 불러오지 못했어요");
  hideScreen(); queryClient.clear();
  const cold = await show("#_obj/axis/i_x1", ["axis", "i_x1", ""]);
  expect(alert(cold)).toContain("축을 불러오지 못했어요");
  expect(cold.querySelector("h2.title")).toBeNull();
});
