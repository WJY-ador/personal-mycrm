// 구조·제안 서랍(옛 test_web_home test_static_trash 서랍 절·test_trash_switch·test_trash_flow 를 옮김, R5b-1) — 정의 필·카드 · 판단 문장 필터 ·
// 서랍(제안 diff·[적용]·[제외] = 서버 action 그대로 · 승격 = 사실 · 근거 빈 자리 · 들어오는 관계 · 이력) · 기준 결정(휴지통 꺼짐 = 옛 버튼 셋, 켜짐 = [남기기]+[삭제]) ·
// [삭제] = r4 §8 확인창 → /api/trash/move(종류·ID·revision) · 축 정책 차단 = 서버 문구 · 실패 = 서버 msg(충돌만 화면 문구).
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { TRASH_ASK } from "../../shared/item";
import { queryClient } from "../../shared/queries";
import { calls, click, installFetch, json, serve, text } from "../../test/fakeServer";
import { byText, hideScreen, reload, showScreen } from "../../test/showScreen";
import { ITEM, structState } from "../../test/structFixture";

const confirm = vi.fn((_a?: string) => true);
let POST: (url: string) => Response = () => json(200, {});
let GET_ITEM: unknown = ITEM;
beforeEach(() => {
  installFetch(); queryClient.clear(); reload.mockClear(); confirm.mockClear(); confirm.mockReturnValue(true); vi.stubGlobal("confirm", confirm);
  vi.stubGlobal("matchMedia", () => ({ matches: false }));
  POST = () => json(200, {}); GET_ITEM = ITEM;
  serve((url, m) => (m === "POST" ? POST(url) : url.startsWith("/api/item") ? json(200, GET_ITEM) : json(404, {})));
});
afterEach(() => { hideScreen(); vi.unstubAllGlobals(); });
const show = (a: string, b = "", s: object = structState()) => showScreen("structure", `#structure/${a}${b ? "/" + b : ""}`, [a, b], s);
const posts = () => calls.filter(c => c.method === "POST").map(c => ({ url: c.url, body: c.body }));

test("정의 필 · 카드(새 제안 먼저 · 칩) · 카드 누르면 그 항목 주소 · 빈 서랍 안내", async () => {
  const el = await show("od_p");
  expect(text(el, "nav.sview a")).toEqual(["항목", "내 구조 설정"]);
  expect(text(el, "nav.sobjs a")).toEqual(["기준2", "판단 문장4", "축1"]);
  expect(text(el, ".asset-card h3")).toEqual(["새 기준 제안", "담당이 먼저", "확정 기준"]);
  expect(text(el, ".asset-card")[0]).toContain("새 제안");
  expect(text(el, ".asset-card:nth-child(2) .top .chip")).toEqual(["P-1", "아직 안 정함", "승격", "근거 1"]);
  expect(el.querySelector("#panel")!.textContent).toBe("카드를 누르면 여기 떠요.");
  await click(el.querySelectorAll(".asset-card")[1]);
  expect(location.hash).toBe("#structure/od_p/p1");
  expect(calls.length).toBe(0);
});

test("서랍 — 제안 diff · 승격 사실 · 근거 빈 자리 · 들어오는 관계 · 이력 · [적용] = 서버 action 그대로", async () => {
  const el = await show("od_p", "p1");
  const p = el.querySelector("#panel")!;
  expect(calls[0].url).toBe("/api/item?id=p1");
  expect(p.querySelector(".eyebrow")!.textContent).toBe("기준 · r2");
  expect(p.querySelector(".promo")!.textContent).toBe("승격 조건 — 확정 근거 1/1 · 충족. 남길지는 내가 정해요.");
  expect(text(p, ".proposal dt")).toEqual(["제목"]);
  expect(p.querySelector(".proposal ins")!.textContent).toBe("담당이 가장 먼저");
  expect(text(p, ".plist li")).toContain("근거를 이용할 수 없어요.");
  expect(text(p, "h5")).toEqual(["근거 2", "결정 1", "이력"]);
  expect(text(p, ".phist")).toEqual([expect.stringMatching(/^r2 · 남김 · /), expect.stringMatching(/^r1 · 적용 · /)]);
  await click(byText(p, "button", "적용")[0]);
  expect(posts()).toEqual([{ url: "/api/item/decide", body: { item_id: "p1", expected_revision: 2, action: "apply", proposal_id: "pr1" } }]);
  expect(p.querySelector(".pstatus")!.textContent).toBe("적용했어요.");
  expect(reload).toHaveBeenCalledTimes(1);
});

test("기준 결정 — 휴지통 꺼짐 = [남기기]·[반영 안 함]·[되돌리기](지금 상태는 꺼짐) · 실패 = 충돌 화면 문구 / 그 밖 서버 msg", async () => {
  GET_ITEM = { ...ITEM, proposal: null };
  const el = await show("od_p", "p1");
  const g = el.querySelector('#panel [role="group"]')!;
  expect(text(g, "button")).toEqual(["남기기", "반영 안 함", "되돌리기"]);
  expect([...g.querySelectorAll("button")].map(b => b.disabled)).toEqual([false, false, true]);
  POST = () => json(400, { code: "CONFLICT", msg: "x" });
  await click(byText(g, "button", "반영 안 함")[0]);
  expect(el.querySelector(".perror")!.textContent).toBe("다른 곳에서 먼저 바뀌었어요. 새로 고침해 다시 봐 주세요.");
  POST = () => json(400, { code: "DAILY-LIMIT", msg: "오늘 한도예요." });
  await click(byText(g, "button", "남기기")[0]);
  expect(el.querySelector(".perror")!.textContent).toBe("오늘 한도예요.");
  expect(posts()[1].body).toEqual({ item_id: "p1", expected_revision: 2, action: "confirm" });
});

test("휴지통 켜짐 — [남기기]+[삭제] · 확인창 취소 = 요청 0 · 삭제 → 목록 주소 + 결과 한 줄 · 축 정책 차단 = 서버 문구", async () => {
  GET_ITEM = { ...ITEM, proposal: null };
  const s = structState({ switches: { trash: true } });
  let el = await show("od_p", "p1", s);
  expect(text(el, '#panel [role="group"] button')).toEqual(["남기기", "삭제"]);
  confirm.mockReturnValue(false);
  await click(byText(el, "button", "삭제")[0]);
  expect(posts()).toEqual([]);
  expect(confirm.mock.calls[0][0]).toBe(TRASH_ASK);
  confirm.mockReturnValue(true);
  POST = () => json(400, { code: "AXIS-IN-POLICY", msg: "이 축은 장치 「회사 PC」의 허용 규칙에 쓰여 삭제할 수 없어요." });
  await click(byText(el, "button", "삭제")[0]);
  expect(el.querySelector(".perror")!.textContent).toBe("이 축은 장치 「회사 PC」의 허용 규칙에 쓰여 삭제할 수 없어요.");
  POST = () => json(200, {});
  await click(byText(el, "button", "삭제")[0]);
  expect(posts().at(-1)).toEqual({ url: "/api/trash/move", body: { kind: "item", id: "p1", expected_revision: 2 } });
  expect(location.hash).toBe("#structure/od_p");
  el = await show("od_p", "", s);
  expect(el.querySelector("#panel")!.textContent).toBe("휴지통으로 옮겼어요.");
  // 확정 기준 = [삭제]만
  GET_ITEM = { ...ITEM, id: "p2", proposal: null, decision: "confirmed" };
  el = await show("od_p", "p2", s);
  expect(text(el, '#panel [role="group"] button')).toEqual(["삭제"]);
});

test("새 항목 제안 [제외] = 카드가 사라짐 → 정의 주소 + 결과 한 줄 · 새 제안엔 [삭제]·결정 버튼 없음", async () => {
  GET_ITEM = { ...ITEM, id: "n1", revision: 0, proposal: { ...ITEM.proposal, proposal_id: "pr_n1" } };
  POST = () => json(200, { deleted: true });
  let el = await show("od_p", "n1", structState({ switches: { trash: true } }));
  expect(el.querySelector("#panel .eyebrow")!.textContent).toBe("기준 · 새 제안");
  expect(el.querySelector("#panel .proposal .hint")!.textContent).toBe("연결한 AI 대화에서 새로 제안한 항목이에요. 적용하면 목록에 들어가요.");
  expect(byText(el, "button", "삭제")).toEqual([]);
  await click(byText(el, "button", "제외")[0]);
  expect(posts()).toEqual([{ url: "/api/item/decide", body: { item_id: "n1", expected_revision: 0, action: "discard", proposal_id: "pr_n1" } }]);
  expect(location.hash).toBe("#structure/od_p");
  el = await show("od_p");
  expect(el.querySelector("#panel")!.textContent).toBe("제안을 제외했어요.");
});

test("판단 문장 — 필터(개수) · 최신순 · 아직 안 정함 = 대조 경로 · 정한 문장 = 근거 원문 · 옛 #structure/<결정> 주소", async () => {
  const el = await show("cand", "pending");
  expect(text(el, 'nav[aria-label="결정 고르기"] a')).toEqual(["확정한 판단1", "아직 안 정함2", "반영 안 함1", "전부4"]);
  expect(text(el, ".asset-card .top")[1]).toContain("⚠️AI 미확정");
  expect(text(el, ".asset-card .top")[1]).toContain("AI 문안");
  await click(el.querySelectorAll(".asset-card")[1]);
  expect(location.hash).toBe("#structure/review/r:r2/c4");
  const done = await showScreen("structure", "#structure/confirmed", ["confirmed", ""], structState());
  expect(done.querySelector('nav[aria-label="결정 고르기"] a.on')!.textContent).toBe("확정한 판단1");
  serve(() => json(200, { id: "r1", title: "도입 메모", body: "입력 **담당**", revision: 1, author_kind: "self", meta: { created: "", source: null, question_id: null } }));
  await click(done.querySelector(".asset-card"));
  expect(calls.at(-1)!.url).toBe("/api/journal?id=r1");
  expect(done.querySelector("dialog.recdlg mark")!.textContent).toBe("입력 담당");
});
