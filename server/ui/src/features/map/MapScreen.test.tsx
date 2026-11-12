// 지도(옛 renderMap) — 세 열 개수 · 대조 경로(탭 id) · 확정 기준 [보기] · 원문 대화창.
import { afterEach, beforeEach, expect, test } from "vitest";
import { queryClient } from "../../shared/queries";
import { calls, click, installFetch, json, serve, text } from "../../test/fakeServer";
import { byText, hideScreen, showScreen } from "../../test/showScreen";
import { JOURNAL, structState } from "../../test/structFixture";

beforeEach(() => { installFetch(); queryClient.clear(); serve(() => json(200, JOURNAL)); });
afterEach(() => hideScreen());

test("칸반 세 열 · [대조] · [보기] · [원문]", async () => {
  const el = await showScreen("map", "#_setup/map", ["map"], structState({ journal: [...structState().journal, { ...structState().journal[0], id: "r3", title: "새 글" }] }));
  expect(text(el, ".kcol h2")).toEqual(["들어오는 것 1", "내 손 대기 2", "쌓이는 재료 2"]);
  expect(el.querySelector(".khint")!.textContent).toBe("AI 대화에서 검토할 판단을 뽑으면 다음 열로");
  expect(text(el, ".kcol")[2]).toContain("내가 남긴 판단과 기준");
  expect(byText(el, "a.btn", "대조")[0].getAttribute("href")).toBe("#map/review/q1/c2");
  expect(byText(el, "a.btn", "대조")[1].getAttribute("href")).toBe("#map/review/r:r2/c4");
  expect(byText(el, "a.btn", "보기")[0].getAttribute("href")).toBe("#structure/od_p/p2");
  await click(byText(el, "button", "원문")[0]);
  expect(calls[0].url).toBe("/api/journal?id=r3");
});

test("못 읽음 = 그 목록 이름", async () => {
  installFetch();
  const el = await showScreen("map", "#_setup/map", ["map"], structState({ read: { journal: { ok: false, error: { code: "OFFLINE", msg: "" } } } }));
  expect(el.querySelector(".partfail b")!.textContent).toBe("내 글 목록을 읽지 못했어요. 나머지는 정상이에요.");
});
