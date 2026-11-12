// 구조·제안 서랍(R5b-1, R5b-2b 에서 적용된 항목 경로 삭제 — 상세·결정·[삭제]는 「나」: MeActs.test.tsx) — 정의 필·카드 · 판단 문장 필터 ·
// 서랍 = 새 항목 제안만([적용]·[제외] = 서버 action 그대로 · 근거 빈 자리) · 실패 = 서버 msg(충돌만 화면 문구).
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { act } from "react";
import { queryClient } from "../../shared/queries";
import { calls, click, flush, installFetch, json, serve, text } from "../../test/fakeServer";
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

const NEW = { ...ITEM, id: "n1", code: null, title: null, body: null, decision: null, revision: 0, links: [], incoming: [], history: [], promotion: null,
  proposal: { ...ITEM.proposal, proposal_id: "pr_n1", title: "새 기준 제안", code: "P-2" } };

test("서랍 = 새 항목 제안만 — 제안 값 · 연결할 대상(근거 빈 자리 포함) · [적용] = 서버 action 그대로 + 상태 다시 받기 · [삭제]·결정 버튼 없음", async () => {
  GET_ITEM = NEW;
  const el = await show("od_p", "n1", structState({ switches: { trash: true } }));
  const p = el.querySelector("#panel")!;
  expect(calls[0].url).toBe("/api/item?id=n1");
  expect(p.querySelector(".eyebrow")!.textContent).toBe("기준, 새 제안");
  expect(p.querySelector("h4")!.textContent).toBe("새 기준 제안");
  expect(p.querySelector(".proposal .hint")!.textContent).toBe("연결한 AI 대화에서 새로 제안한 항목이에요. 적용하면 목록에 들어가요.");
  expect(text(p, ".plist li")).toContain("근거를 이용할 수 없어요.");
  expect(p.querySelector(".promo")).toBeNull();
  expect(p.querySelector(".phist")).toBeNull();
  expect(text(p, "button")).toEqual(["적용", "제외"]);
  await click(byText(p, "button", "적용")[0]);
  expect(posts()).toEqual([{ url: "/api/item/decide", body: { item_id: "n1", expected_revision: 0, action: "apply", proposal_id: "pr_n1" } }]);
  expect(p.querySelector(".pstatus")!.textContent).toBe("적용했어요.");
  expect(reload).toHaveBeenCalledTimes(1);   // 적용된 항목 = 라우터가 「나」 로 replace(shared/route.test.ts)
});

test("적용된 항목 주소 = 서랍 없음(「나」 에서 본다 — 라우터 replace) · 실패 = 충돌 화면 문구 / 그 밖 서버 msg", async () => {
  const el = await show("od_p", "p1");
  expect(el.querySelector("#panel")!.textContent).toBe("카드를 누르면 여기 떠요.");
  expect(calls.length).toBe(0);
  GET_ITEM = NEW;
  const e2 = await show("od_p", "n1");
  POST = () => json(400, { code: "CONFLICT", msg: "x" });
  await click(byText(e2, "button", "적용")[0]);
  expect(e2.querySelector(".perror")!.textContent).toBe("다른 곳에서 먼저 바뀌었어요. 새로 고침해 다시 봐 주세요.");
  POST = () => json(400, { code: "DAILY-LIMIT", msg: "오늘 한도예요." });
  await click(byText(e2, "button", "제외")[0]);
  expect(e2.querySelector(".perror")!.textContent).toBe("오늘 한도예요.");
});

test("새 항목 제안 [제외] = 카드가 사라짐 → 정의 주소 + 결과 한 줄", async () => {
  GET_ITEM = NEW;
  POST = () => json(200, { deleted: true });
  let el = await show("od_p", "n1");
  await click(byText(el, "button", "제외")[0]);
  expect(posts()).toEqual([{ url: "/api/item/decide", body: { item_id: "n1", expected_revision: 0, action: "discard", proposal_id: "pr_n1" } }]);
  expect(location.hash).toBe("#structure/od_p");
  el = await show("od_p");
  expect(el.querySelector("#panel")!.textContent).toBe("제안을 제외했어요.");
});

test("판단 문장 — 필터(개수) · 최신순 · 아직 안 정함 = 대조 경로 · 정한 문장 = 근거 원문 · 옛 #structure/<결정> 주소", async () => {
  const el = await show("cand", "pending");
  expect(text(el, 'nav[aria-label="결정 고르기"] a')).toEqual(["확정한 판단1", "아직 안 정함2", "반영 안 함1", "전부4"]);
  expect(text(el, ".asset-card .top")[1]).toContain("AI 미확정");
  expect(el.querySelector(".asset-card .chip.flag svg")!.getAttribute("aria-label")).toBe("주의");
  expect(text(el, ".asset-card .top")[1]).toContain("AI 문안");
  const pending = el.querySelectorAll(".asset-card")[1];
  expect(pending.getAttribute("role")).toBeNull();
  expect(pending.querySelector("button")?.textContent).toBe("원문 보기: 회고");
  const compare = [...pending.querySelectorAll("a, button")].find(control => control.textContent === "대조하기");
  expect(compare?.textContent).toBe("대조하기");
  expect(compare?.tagName).toBe("BUTTON");
  expect(compare?.getAttribute("role")).toBeNull();
  expect((compare as HTMLButtonElement).tabIndex).toBe(0);
  await click(pending.querySelector("h3"));
  expect(location.hash).toBe("#structure/review/r:r2/c4");
  await click(compare);
  expect(location.hash).toBe("#structure/review/r:r2/c4");
  const done = await showScreen("structure", "#structure/confirmed", ["confirmed", ""], structState());
  expect(done.querySelector('nav[aria-label="결정 고르기"] a.on')!.textContent).toBe("확정한 판단1");
  const confirmed = done.querySelector(".asset-card")!;
  expect(confirmed.getAttribute("role")).toBeNull();
  const sourceAction = confirmed.querySelector("button");
  expect(sourceAction?.textContent).toBe("원문 보기: 도입 메모");
  expect(confirmed.querySelectorAll("button")).toHaveLength(1);
  serve(() => json(200, { id: "r1", title: "도입 메모", body: "입력 **담당**", revision: 1, author_kind: "self", meta: { created: "", source: null, question_id: null } }));
  await click(confirmed.querySelector("h3"));
  expect(calls.at(-1)!.url).toBe("/api/journal?id=r1");
  expect(done.querySelector("dialog.recdlg mark")!.textContent).toBe("입력 담당");
  const dialog = done.querySelector("dialog.recdlg")!;
  const anotherControl = done.querySelector('nav[aria-label="결정 고르기"] a.on') as HTMLElement;
  anotherControl.focus();
  await click(done.querySelector("dialog [data-close]"));
  await act(async () => { dialog.dispatchEvent(new Event("close")); });
  expect(document.activeElement).toBe(sourceAction);
  await click(sourceAction);
  expect(calls.at(-1)!.url).toBe("/api/journal?id=r1");
  expect(done.querySelector("dialog.recdlg mark")!.textContent).toBe("입력 담당");
  expect(done.querySelectorAll(".asset-card button")).toHaveLength(1);
  expect(calls.filter(call => call.url === "/api/journal?id=r1")).toHaveLength(1);
});

test("원문 모달을 연 카드가 목록에서 사라지면 닫을 때 현재 결정 필터로 포커스 복귀", async () => {
  const initial = structState();
  let el = await show("cand", "confirmed", initial);
  await click(el.querySelector(".asset-card h3"));
  const remaining = { ...initial, candidates: initial.candidates.filter(c => c.id !== "c1") };
  el = await show("cand", "confirmed", remaining);
  const filter = el.querySelector('nav[aria-label="결정 고르기"] a.on');
  const dialog = el.querySelector("dialog.recdlg")!;
  await click(el.querySelector("dialog [data-close]"));
  await act(async () => { dialog.dispatchEvent(new Event("close")); });
  expect(document.activeElement).toBe(filter);
});

test("서랍 다시 받기 실패 = 받아 둔 제안 그대로 + 못 읽음 안내(가짜 서버만)", async () => {
  GET_ITEM = NEW;
  const el = await show("od_p", "n1");
  const p = el.querySelector("#panel")!;
  expect(p.querySelector("h4")!.textContent).toBe("새 기준 제안");
  expect(p.querySelector(".partfail")).toBeNull();
  const before = calls.filter(c => c.url === "/api/item?id=n1").length;
  serve((url, m) => (m === "GET" && url.startsWith("/api/item") ? json(503, { code: "OFFLINE", msg: "" }) : json(404, {})));
  await act(async () => { await queryClient.invalidateQueries({ queryKey: ["item", "n1"], exact: true }); });
  await flush();
  expect(calls.filter(c => c.url === "/api/item?id=n1").length).toBe(before + 1);
  expect(queryClient.getQueryState(["item", "n1"])?.status).toBe("error");
  expect(p.querySelector(".eyebrow")!.textContent).toBe("기준, 새 제안");
  expect(p.querySelector("h4")!.textContent).toBe("새 기준 제안");
  expect(p.querySelector(".partfail b")!.textContent).toBe("이 항목을 읽지 못했어요. 나머지는 정상이에요.");
  expect(p.querySelector(".partfail")!.textContent).toContain("서버에 연결하지 못했어요.");
});
