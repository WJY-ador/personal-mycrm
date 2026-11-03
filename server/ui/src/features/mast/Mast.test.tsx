// 마스트(옛 mast) — 스펙트럼(비율 = 개수, 0 칸 없음) · 범례 · 질문 레전드(미결정 · [한 장] = 첫 질문형 탭) · 질문 없는 미결정 · 비면 숨김.
import { afterEach, expect, test } from "vitest";
import { click, installFetch, text } from "../../test/fakeServer";
import { hideScreen, showScreen } from "../../test/showScreen";
import { structState } from "../../test/structFixture";

afterEach(() => hideScreen());

test("스펙트럼 · 레전드 · [한 장] · 질문 없음", async () => {
  installFetch();
  const el = await showScreen("mast", "#structure", [], structState({ tabs: [{ id: "t-001", label: "내 질문", blocks: ["sheet"] }] }));
  expect(el.querySelector("#axistop")!.hasAttribute("hidden")).toBe(false);
  expect(el.querySelector("#spectrum")!.getAttribute("aria-label")).toBe("확정한 판단 1 · 아직 안 정함 2 · 반영 안 함 1 · 판단이 없는 글 0");
  expect(el.querySelectorAll("#spectrum div").length).toBe(3);
  expect(text(el, "#legend .ax b")).toEqual(["Q1", "Q2", "—"]);
  expect(text(el, "#legend em")).toEqual(["미결정 1", "미결정 0", "미결정 1"]);
  await click(el.querySelector("#legend button"));
  expect(location.hash).toBe("#t-001/q1");
  const empty = await showScreen("mast", "#q", [], structState({ candidates: [], journal: [], questions: [] }));
  expect(empty.querySelector("#axistop")!.hasAttribute("hidden")).toBe(true);
  expect(empty.querySelector("#legend")!.textContent).toBe("질문이 아직 없어요");
});
