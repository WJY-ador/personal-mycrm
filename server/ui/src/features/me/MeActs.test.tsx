// 「나」 상세 동작 칸(옛 test_web_home.py test_trash_switch·test_trash_flow 의 homeActs 절을 옮김) — 휴지통 스위치별 버튼 ·
// 기준 [남기기]+[삭제] · 판단 [삭제] 0 · [삭제] = 확인창(r4 문구) → /api/trash/move → 목록 주소 + 결과 한 줄 · 축 정책 차단 = 서버 안내 그대로.
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { queryClient } from "../../shared/queries";
import { calls, click, installFetch, json, serve } from "../../test/fakeServer";
import { installMedia, JOURNAL, layout, meState, STATS } from "../../test/meFixture";
import { btn, btns, hideMe, reload, showMe } from "../../test/showMe";
import { TRASH_ASK } from "./text";

let POST: () => Response = () => json(200, {});
beforeEach(() => {
  installFetch(); installMedia(false); queryClient.clear(); reload.mockClear();
  POST = () => json(200, {});
  serve((url, m) => (m === "POST" ? POST() : url === "/api/me/layout" ? json(200, layout()) : url === "/api/me/stats" ? json(200, STATS)
    : url.startsWith("/api/journal") ? json(200, JOURNAL) : json(200, { activities: [], activity_count: 0 })));
});
afterEach(() => { hideMe(); vi.unstubAllGlobals(); });
const posts = () => calls.filter(c => c.method === "POST");
const S = (trash: boolean, items: unknown[] = meState().items) => meState({ switches: { trash }, user: { display_name: "홍길동", nav: "new" }, items });
const withDecision = (d: string): unknown[] => meState().items.map(it => (it.id === "p1" ? { ...it, decision: d } : it));

test("휴지통 꺼짐 — 기준 = 옛 버튼(글자만 「반영 안 함」) · [삭제] 0", async () => {
  for (const s of [S(false)]) {
    let el = await showMe("#_me/principle/p1", { ...s, items: withDecision("pending") });
    expect(btns(el)).toEqual(["남기기", "반영 안 함"]);
    el = await showMe("#_me/principle/p1", { ...s, items: withDecision("confirmed") });
    expect(btns(el)).toEqual(["반영 안 함", "되돌리기"]);
    el = await showMe("#_me/principle/p1", { ...s, items: withDecision("excluded") });
    expect(btns(el)).toEqual(["남기기", "되돌리기"]);
    el = await showMe("#_me/journal/r1", s);
    expect(btns(el)).toEqual([]);
    el = await showMe("#_me/refl/f1", s);
    expect(btns(el)).toEqual(["확인했어요"]);
  }
});

test("휴지통 켜짐 — 기준 [남기기]+[삭제](확정이면 [삭제]만) · 내 글·생각·다른 항목 [삭제] · 판단 [삭제] 0(기존 결정 그대로)", async () => {
  let el = await showMe("#_me/principle/p1", S(true, withDecision("pending")));
  expect(btns(el)).toEqual(["남기기", "삭제"]);
  el = await showMe("#_me/principle/p1", S(true, withDecision("confirmed")));
  expect(btns(el)).toEqual(["삭제"]);
  el = await showMe("#_me/journal/r1", S(true));
  expect(btns(el)).toEqual(["삭제"]);
  el = await showMe("#_me/refl/f1", S(true));
  expect(btns(el)).toEqual(["확인했어요", "삭제"]);
  el = await showMe("#_me/axis/a1", S(true));
  expect(btns(el)).toEqual(["삭제"]);
  el = await showMe("#_me/cand/c1", S(true));
  expect(btns(el)).toEqual(["남기기", "고쳐서 남기기", "반영 안 함"]);
});

test("[삭제] — 확인창(r4 §8 글자 그대로) · 취소 = 요청 0 · 확인 = 종류·ID·revision → 목록 주소 + 「휴지통으로 옮겼어요.」", async () => {
  const ask = vi.fn(() => false);
  vi.stubGlobal("confirm", ask);
  let el = await showMe("#_me/principle/p1", S(true));
  await click(btn(el, "삭제"));
  expect(ask).toHaveBeenCalledWith(TRASH_ASK);
  expect(posts()).toEqual([]);
  ask.mockReturnValue(true);
  await click(btn(el, "삭제"));
  expect(posts()).toEqual([{ url: "/api/trash/move", method: "POST", body: { kind: "item", id: "p1", expected_revision: 2 } }]);
  expect(location.hash).toBe("#_me/principle");
  expect(reload).toHaveBeenCalledTimes(1);
  await showMe("#_me/principle", S(true));   // 껍데기가 새 주소로 다시 띄움 → 「나」가 연결 최다 항목으로 replace
  expect(location.hash).toBe("#_me/principle/p1");
  el = await showMe(location.hash, S(true));
  expect(el.querySelector("#core-msg")!.textContent).toBe("휴지통으로 옮겼어요.");   // replace 뒤에도 한 번(옛 coreFlash 와 같다)
  el = await showMe("#_me/principle/p2", S(true));
  expect(el.querySelector("#core-msg")!.textContent).toBe("");   // 다른 곳으로 가면 사라진다
  el = await showMe("#_me/journal/r1", S(true));
  await click(btn(el, "삭제"));
  expect(posts().at(-1)!.body).toEqual({ kind: "record", id: "r1" });   // revision 없는 종류 = expected_revision 생략
});

test("[삭제] 축 정책 차단 = 서버 장치 안내 그대로 · 이동 0", async () => {
  vi.stubGlobal("confirm", () => true);
  POST = () => json(400, { code: "AXIS-IN-POLICY", msg: "이 축은 장치 「회사 PC」의 허용 규칙에 쓰여 삭제할 수 없어요." });
  const el = await showMe("#_me/axis/a1", S(true));
  await click(btn(el, "삭제"));
  expect(el.querySelector("#home-detail .ferr")!.textContent).toBe("이 축은 장치 「회사 PC」의 허용 규칙에 쓰여 삭제할 수 없어요.");
  expect(location.hash).toBe("#_me/axis/a1");
});

test("판단 [남기기] = 그 자리 문구 · [반영 안 함] = 목록 주소 + 결과 한 줄 · 실패 = 원인 + 다음 행동", async () => {
  let el = await showMe("#_me/cand/c1", S(true));
  await click(btn(el, "남기기"));
  expect(posts().at(-1)).toEqual({ url: "/api/candidate/decide", method: "POST", body: { candidate_id: "c1", action: "confirm", expected_revision: 1 } });
  expect(el.querySelector("#home-detail .fok")!.textContent).toBe("확정한 판단으로 남겼어요.");
  el = await showMe("#_me/cand/c1", S(true));
  await click(btn(el, "반영 안 함"));
  expect(location.hash).toBe("#_me");
  el = await showMe("#_me", S(true));
  expect(el.querySelector("#core-msg")!.textContent).toBe("반영 안 함으로 표시했어요. 목록에서 빠졌어요.");
  POST = () => json(400, { code: "CANDIDATE-REVIEW", msg: "근거 글이 남이 쓴 글이에요." });
  el = await showMe("#_me/cand/c1", S(true));
  await click(btn(el, "남기기"));
  expect(el.querySelector("#home-detail .ferr")!.textContent).toBe("근거 글이 남이 쓴 글이에요. 반영 안 함으로는 표시할 수 있어요.");
});

test("껍데기 결과 한 줄(ctx.flash — 새 탐색 수락 등) = 머리에 한 번", async () => {
  const el = await showMe("#_me/summary", S(true), { text: "새 탐색으로 바꿨어요." });
  expect(el.querySelector("#core-msg")!.textContent).toBe("새 탐색으로 바꿨어요.");
});
