// 내 구조 설정 추천 칸(2026-11-18 구조추천 명세 6.5) — 초안 카드(이름, 필드, 담을 규칙 문장, 견본 = 원문 글자 그대로, 채워질 건수는 route 있는 초안만)
// · [적용] [이름 고치기] [빼기](확인 한 번) 요청 모양 · 충돌 = 머리 한 줄 + 다시 받기 · 실패 = 그 카드에 서버 문구 · 구조 추천 받기 = 웹 대화에 정해진 요청(꺼짐 = 안내 한 줄).
import { act } from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { aiAsk } from "../../shared/aiAsk";
import { queryClient } from "../../shared/queries";
import { calls, click, flush, installFetch, json, serve, text } from "../../test/fakeServer";
import { byText, hideScreen, reload, showScreen } from "../../test/showScreen";
import { structState } from "../../test/structFixture";
import sample from "./reco.sample.json";

let POST: (url: string) => Response = () => json(200, {});
beforeEach(() => {
  installFetch(); queryClient.clear(); reload.mockClear(); POST = () => json(200, {});
  serve((url, m) => (m === "POST" ? POST(url) : url === "/api/structure/reco" ? json(200, sample) : json(404, {})));
});
afterEach(() => { hideScreen(); vi.unstubAllGlobals(); });
const show = (webchat = true) => showScreen("defs", "#_setup/structure", [], structState({ switches: { trash: false, webchat } }));
const posts = () => calls.filter(c => c.method === "POST").map(c => ({ url: c.url, body: c.body }));
const card = (el: Element, i: number) => el.querySelectorAll("#reco article")[i];
const d0 = { object_id: "od_sample0001", proposal_id: "dp_sample0001" };

test("카드 — 이름, 필드(뽑는 곳), 담을 규칙 문장, 견본(제목 + 원문 글자 그대로), 채워질 건수 · route 없는 초안 = 건수 줄 없음", async () => {
  const el = await show();
  expect(el.querySelector("#reco-title")!.textContent).toBe("추천2");
  expect(el.querySelector("#reco")!.compareDocumentPosition(el.querySelector(".dmode")!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();   // 맨 위
  const c = card(el, 0);
  expect(c.querySelector("h4")!.textContent).toBe("피벗pivots결정");
  expect(text(c, "dt")).toEqual(["필드", "담을 규칙", "견본"]);
  expect(text(c, "dd")[0]).toBe("날짜(기록 날짜), 어디서(라벨 어디서), 결정(라벨 결정)");
  expect(text(c, "dd")[1]).toBe(sample.drafts[0].rule);
  expect(text(c, "li b")).toEqual(["P1. 가짜 피벗 1", "P2. 가짜 피벗 2"]);
  expect(text(c, "blockquote")[1]).toBe(sample.drafts[0].samples[1].quote);   // 태그는 글자로
  expect(el.querySelector("#reco img, #reco script")).toBeNull();
  expect(c.textContent).toContain("적용하면 4건이 채워져요, 1건은 분류 못 해요.");
  expect(text(c, ".acts button")).toEqual(["적용", "이름 고치기", "빼기"]);
  const n = card(el, 1);
  expect(n.textContent).not.toContain("적용하면");
  expect(text(n, "dd")).toEqual(["필드가 없어요.", "담을 규칙이 없어요. 적용해도 저절로 담기지 않아요."]);
  expect(el.querySelector("#reco")!.textContent).toContain("어느 자료 종류에도 안 붙은 기록이 31편 있어요.");
  expect(el.textContent).not.toMatch(/[「」·]/);   // 새 화면 글에 낫표, 가운뎃점 없음
});

test("[적용] = POST apply {object_id, proposal_id, expected_revision} → 머리 한 줄 + 다시 받기", async () => {
  POST = () => json(200, { route_sync: { created: 4, updated: 0, removed: 0, partial: 1, left: 0 } });
  const el = await show();
  await click(byText(card(el, 0), "button", "적용")[0]);
  expect(posts()).toEqual([{ url: "/api/structure/drafts/apply", body: { ...d0, expected_revision: 0 } }]);
  expect(el.querySelector("#reco-msg")!.textContent).toBe("피벗: 적용했어요. 4건을 채웠어요.");
  expect(reload).toHaveBeenCalledTimes(1);
  expect(calls.filter(c => c.url === "/api/structure/reco").length).toBe(2);
});

test("[이름 고치기] = 새 이름 칸 → POST rename {.., label} · 같은 이름이면 저장 꺼짐 · 취소 = 요청 0", async () => {
  const el = await show();
  await click(byText(card(el, 0), "button", "이름 고치기")[0]);
  const input = card(el, 0).querySelector("input")!;
  expect(input.value).toBe("피벗");
  expect(byText(card(el, 0), "button", "저장")[0].hasAttribute("disabled")).toBe(true);
  const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
  await act(async () => { set.call(input, " 전환점 "); input.dispatchEvent(new Event("input", { bubbles: true })); });
  await click(byText(card(el, 0), "button", "저장")[0]);
  expect(posts()).toEqual([{ url: "/api/structure/drafts/rename", body: { ...d0, expected_revision: 0, label: "전환점" } }]);
  expect(el.querySelector("#reco-msg")!.textContent).toBe("피벗: 이름을 고쳤어요.");
});

test("[빼기] = 확인 한 번(취소 = 요청 0) → POST discard · 충돌 = 머리 한 줄 · 그 밖 실패 = 카드에 서버 문구", async () => {
  const ask = vi.fn(() => false);
  vi.stubGlobal("confirm", ask);
  const el = await show();
  await click(byText(card(el, 1), "button", "빼기")[0]);
  expect(posts()).toEqual([]);
  ask.mockReturnValue(true);
  POST = () => json(400, { code: "CONFLICT", msg: "지금 revision 1" });
  await click(byText(card(el, 0), "button", "빼기")[0]);
  expect(posts()).toEqual([{ url: "/api/structure/drafts/discard", body: d0 }]);
  expect(el.querySelector("#reco-msg")!.textContent).toBe("피벗: 다른 곳에서 먼저 바뀌었어요. 추천을 다시 불러왔어요.");
  POST = () => json(400, { code: "ARG-INVALID", msg: "이 초안을 가리키는 것이 있어 지울 수 없어요." });
  await click(byText(card(el, 0), "button", "빼기")[0]);
  expect(card(el, 0).querySelector(".perror")!.textContent).toBe("이 초안을 가리키는 것이 있어 지울 수 없어요.");
});

test("구조 추천 받기 — 웹 대화 켜짐 = 정해진 요청을 대화에 넘김 · 꺼짐 = 버튼 대신 안내 한 줄", async () => {
  const got: string[] = [];
  const off = aiAsk.on(t => got.push(t));
  let el = await show(true);
  await click(byText(el, "button", "구조 추천 받기")[0]);
  expect(got).toEqual(["내 기록을 보고 구조를 추천해 줘"]);
  expect(posts()).toEqual([]);
  off(); hideScreen();
  el = await show(false);
  expect(byText(el, "button", "구조 추천 받기")).toEqual([]);
  expect(el.querySelector("#reco")!.textContent).toContain('연결한 AI 대화에서 "내 기록을 보고 구조를 추천해 줘"라고 말해 보세요.');
  await flush();
});

test("껍데기가 상태를 다시 받으면(generated 바뀜) 추천도 다시 받는다 — 대화에서 생긴 초안이 새로 고침 없이 보인다", async () => {
  await showScreen("defs", "#_setup/structure", [], structState({ generated: "2026-11-18T09:00:00+00:00" }));
  await showScreen("defs", "#_setup/structure", [], structState({ generated: "2026-11-18T09:01:00+00:00" }));
  expect(calls.filter(c => c.url === "/api/structure/reco").length).toBe(2);
});
