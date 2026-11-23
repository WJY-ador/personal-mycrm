// 판단 검토(원문과 대조하기) — 옛 app.html renderReview·decide 동작을 옮긴 시험(R3). 껍데기 라우터 대신 주소(history)와 ctx(상태·args)를 직접 넘긴다.
// 2026-11-23: 한 장씩이 아니라 범위의 미결 문장을 카드로 나열. 카드 = 문장(눌러서 고치기) + 근거 원문 + [남기기] [남기지 않기].
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { SCREENS } from "../../test/screens";
import { Card } from "./Card";
import { useDirtyCards } from "./ReviewScreen";
import { WORDS } from "./text";
import { queryClient } from "../../shared/queries";
import type { AppState } from "../../shared/state";
import { calls, click, flush, installFetch, json, serve } from "../../test/fakeServer";
import { reload as appReload, reloadState, useAppState } from "../../layout/useAppState";

const BODY = "# 도입 회고\n\n첫 문단이다.\n\n고객은 입력 담당을 먼저 정했다. 그게 맞았다.\n\n셋째 문단.\n\n넷째 문단은 멀다.";
const J = { id: "r1", title: "도입 회고", body: BODY, revision: 1, author_kind: "self", meta: { created: "2026-11-02T01:00:00Z", source: "파일:a.md", question_id: "q1" } };
const cand = (id: string, x: object = {}) => ({ id, text: "담당을 먼저 정한다 " + id, status: "pending", record_id: "r1", question_id: "q1", quote: "입력 담당을 먼저",
  review: null, revision: 2, created: "2026-11-02T01:00:00Z", origin: "ai", edited_by_user: false, wording_by: "ai", wording_approved: false, ...x });
const state = (cands: object[], x: object = {}) => ({
  user: { display_name: "홍길동", nav: "new" }, switches: { trash: true }, questions: [{ id: "q1", text: "도입 순서는?", created: "" }],
  journal_next_before: null,
  journal: [{ id: "r1", title: "도입 회고", excerpt: "", created: "", source: null, source_id: "s1", question_id: "q1", source_date: null, author_kind: "self" }],
  sources: [{ id: "s1", kind: "file", name: "회고 메모", location: null }], candidates: cands, ...x }) as unknown as AppState;

let el: HTMLDivElement, root: Root, S: AppState, args: string[];
const reload = vi.fn(async () => true);
const setDirty = vi.fn();
async function show(st: AppState, key: string, qid = "q1") {
  S = st; args = ["q", qid, key, "#q/q1", "질문으로 돌아가기"];
  history.replaceState(null, "", `#q/review/${qid}/${key}`);
  const R = SCREENS.review;
  await act(async () => root.render(<QueryClientProvider client={queryClient}><R ctx={{ reload, setDirty, state: S, args }} /></QueryClientProvider>));
  await flush(); await flush();
}
const redraw = () => show(S, args[2], args[1]);   // 껍데기 render() — reload 가 받은 새 상태로 다시 그린다
const btn = (t: string) => [...el.querySelectorAll("button")].find(b => b.textContent === t) as HTMLButtonElement;
// 카드 하나 — 문장 버튼(눌러서 고치기), 카드 안 버튼, 카드의 저장 문구(status, error), 앞 카드가 빠진 결과 한 줄(lead)
const card = (id: string) => el.querySelector(`#cand-${id}`) as HTMLElement;
const inCard = (id: string, t: string) => [...card(id).querySelectorAll("button")].find(b => b.textContent === t) as HTMLButtonElement;
const sentBtn = (id = "c_1") => card(id).querySelector("button[title='눌러서 고치기']") as HTMLButtonElement;
const stat = (id = "c_1") => el.querySelector(`#save-status-${id}`)!.textContent;
const err = (id = "c_1") => el.querySelector(`#save-error-${id}`)!.textContent;
const lead = (id: string) => el.querySelector(`#lead-${id}`)!.textContent;
const ids = () => [...el.querySelectorAll("[data-candidate-id]")].map(x => x.getAttribute("data-candidate-id"));
const posts = () => calls.filter(c => c.method === "POST");

let POST: () => Response | Promise<Response> = () => json(200, {});
beforeEach(() => {
  installFetch(); queryClient.clear(); reload.mockReset(); reload.mockResolvedValue(true); setDirty.mockReset();
  POST = () => json(200, {});
  serve((url, m) => (m === "POST" ? POST() : url.startsWith("/api/journal") ? json(200, J) : json(404, {})));
  el = document.createElement("div"); document.body.append(el); root = createRoot(el);
});
afterEach(() => { act(() => root.unmount()); el.remove(); vi.unstubAllGlobals(); });

test("나열 — 질문과 결정 설명은 머리에 한 번, 카드마다 문장, 칩, 재검토 0, 근거 원문(구절 문단 ±1 흐림, mark, 전체 원문, 기술 정보), 원문 확인 뒤에만 결정 버튼과 문장 고치기", async () => {
  serve((_u, m) => (m === "POST" ? POST() : new Promise(() => {})));   // 원문을 아직 못 받음
  await show(state([cand("c_1"), cand("c_2")]), "c_1");
  expect(el.querySelector("h2")!.textContent).toBe("원문과 대조하기");
  expect(el.textContent).toContain("아직 안 정한 문장 2개");
  expect(el.querySelector("a.link")!.getAttribute("href")).toBe("#q/q1");
  expect(ids()).toEqual(["c_1", "c_2"]);   // 한 장씩이 아니라 전부
  expect(el.textContent.match(/질문: 도입 순서는\?/g)).toHaveLength(1);   // 질문은 머리에 한 번, 카드에는 없다
  expect(el.querySelector("[data-candidate-id]")!.textContent).not.toContain("질문:");
  expect(el.querySelectorAll("#decision-help")).toHaveLength(1);
  expect(el.querySelector("#decision-help")!.textContent).toBe("남기면 이 질문의 확정한 판단에 들어가고, 남기지 않음으로 둬도 판단 문장과 원문은 삭제되지 않아요.");
  expect([...card("c_1").querySelectorAll(".labels > *")].map(x => x.textContent)).toEqual(["AI가 쓴 문장"]);   // AI 표시 하나(디자인 2 C3)
  expect(el.querySelector(".recheck")).toBeNull();
  expect([...card("c_1").querySelectorAll(".acts[role=group] button")].map(b => b.textContent)).toEqual(["남기기", "남기지 않기"]);   // 결정 버튼 둘
  expect(["고쳐서 남기기", "이전 문장", "건너뛰기"].map(t => btn(t))).toEqual([undefined, undefined, undefined]);
  expect(el.textContent).not.toContain("건너뛰어도");
  expect(["남기기", "남기지 않기"].map(t => btn(t).disabled)).toEqual([true, true]);
  expect(sentBtn().disabled).toBe(true);   // 원문 확인 전엔 문장도 못 고친다(고친 문장 저장 = 확정)
  expect(el.textContent).toContain("원문을 불러오는 중이에요…");
  serve(() => json(200, J)); queryClient.clear();
  await show(state([cand("c_1"), cand("c_2")]), "c_1");
  expect(["남기기", "남기지 않기"].map(t => btn(t).disabled)).toEqual([false, false]);
  expect(sentBtn().disabled).toBe(false);
  expect(sentBtn().textContent).toBe("담당을 먼저 정한다 c_1");
  expect(sentBtn().querySelector("svg[aria-label='고치기']")).not.toBeNull();   // 연필 표시 = shared EditMark
  expect(el.querySelectorAll("[id^='rvsrc-']")).toHaveLength(2);   // 근거 원문도 카드마다
  const src = el.querySelector("#rvsrc-c_1")!;
  expect(src.querySelector("h4")!.textContent).toBe("근거 원문: 도입 회고");
  const ex = src.querySelector(":scope > .doc")!;
  expect([...ex.querySelectorAll("p")].map(p => [p.className, p.textContent])).toEqual([
    ["dim", "첫 문단이다."], ["", "고객은 입력 담당을 먼저 정했다. 그게 맞았다."], ["dim", "셋째 문단."]]);
  expect(ex.querySelector("mark")!.textContent).toBe("입력 담당을 먼저");
  expect(src.querySelector("details.fold summary")!.textContent).toBe("전체 원문 보기");
  expect(src.querySelector("details.tech")!.textContent).toContain("출처 회고 메모(파일), 쓸 당시 표기 파일에서 가져옴, 근거 구절 9자");
});

test("AI 표시는 하나(디자인 2 C3) — AI가 쓴 문장 = 배지 하나 + 점선 표시, 내 메모 = AI 표시 없음, 내 메모 + 승인 전 AI 문안 = AI 문안 하나 + 점선 표시", async () => {
  const shown = () => ({ labels: [...el.querySelectorAll(".labels > *")].map(x => x.textContent), marked: el.querySelector("[data-candidate-id]")!.classList.length === 2 });
  await show(state([cand("c_1")]), "c_1");
  expect(shown()).toEqual({ labels: ["AI가 쓴 문장"], marked: true });
  await show(state([cand("c_1", { origin: "memo", wording_by: "user", wording_approved: true })]), "c_1");
  expect(shown()).toEqual({ labels: ["내가 쓴 메모"], marked: false });
  await show(state([cand("c_1", { origin: "memo", wording_by: "ai", wording_approved: false })]), "c_1");
  expect(shown()).toEqual({ labels: ["내가 쓴 메모", "AI 문안"], marked: true });
});

test("근거 구절이 원문에 없음·원문 못 받음 = 경고, 결정 잠김 · 문단 경계 = 전체 원문 + 버튼 켜짐 · 재검토 표시", async () => {
  await show(state([cand("c_1", { quote: "없는 구절" })]), "c_1");
  expect(el.querySelector("#rvsrc-c_1")!.textContent).toContain("이 판단의 근거 구절이 저장된 원문과 일치하지 않아 남길 수 없어요. 찾던 구절: 없는 구절");
  expect(btn("남기기").disabled).toBe(true);
  queryClient.clear(); serve(() => json(404, { code: "RECORD-MISSING", msg: "없음" }));
  await show(state([cand("c_1")]), "c_1");
  expect(el.querySelector("#rvsrc-c_1")!.textContent).toContain("원문을 불러오지 못했어요. 근거를 확인할 수 없어 남길 수 없어요. 새로 고침해도 그대로면 다시 로그인해 보세요.");
  expect(el.querySelector("#rvsrc-c_1 code")!.textContent).toBe("RECORD-MISSING");
  expect(btn("남기기").disabled).toBe(true);
  queryClient.clear(); serve(() => json(200, J));
  await show(state([cand("c_1", { quote: "다.\n\n고객은", review: "external" })]), "c_1");
  expect(el.querySelector("#rvsrc-c_1")!.textContent).toContain("근거 구절이 문단 경계에 걸쳐 있어 위치를 강조하지 못했어요.");
  expect(btn("남기기").disabled).toBe(false);
  expect(el.querySelector(".recheck")!.textContent).toContain("근거 글이 남이 쓴 글이라 이 판단을 확정할 수 없어요.");
});

test("주소 — 빈 자리, 옛 숫자, 넘친 숫자, end, 정한 판단 = 주소를 고치지 않고 목록 맨 위, 목록의 후보 = 그 카드로 포커스, 빈 목록, 기록 범위", async () => {
  const st = state([cand("c_1"), cand("c_2"), cand("c_x", { question_id: "q2" })]);
  for (const k of ["", "1", "9", "end", "c_gone"]) {
    await show(st, k);
    expect(location.hash).toBe(`#q/review/q1/${k}`);
    expect(ids()).toEqual(["c_1", "c_2"]);
    expect(document.activeElement).toBe(document.body);
    expect(el.textContent).not.toContain("목록 끝이에요");
  }
  await show(st, "c_2");
  expect(document.activeElement).toBe(card("c_2"));   // 그 카드로 스크롤과 포커스
  sentBtn("c_1").focus();
  await show(state([cand("c_1"), cand("c_2")]), "c_2");   // 주기 갱신(새 상태, 같은 주소)은 포커스를 다시 옮기지 않는다
  expect(document.activeElement).toBe(sentBtn("c_1"));
  await show(state([]), "c_1");
  expect(el.textContent).toContain("아직 안 정한 문장이 없어요.이 질문의 미결 문장 검토가 끝났어요.새 글에서 판단을 뽑으면 여기에 떠요.");
  await show(state([cand("c_9", { question_id: null })]), "c_9", "r:r1");
  expect(el.textContent).toContain("질문 없음, 내 글: 도입 회고");
  expect(el.querySelector("[data-candidate-id]")!.textContent).not.toContain("질문 없음");
  expect(el.querySelector("#decision-help")!.textContent).toBe("남기면 확정한 판단에 들어가고(질문 없음), 남기지 않음으로 둬도 판단 문장과 원문은 삭제되지 않아요.");
  await show(state([], { read: { candidates: { ok: false, error: { code: "OFFLINE", msg: "x" } } } }), "c_1");
  expect(el.querySelector(".partfail")!.textContent).toContain("문장 목록을 읽지 못했어요. 나머지는 정상이에요.서버에 연결하지 못했어요.");
});

test("남기기 — 호출 하나(expected_revision), 저장 중 모든 카드 잠금, 새 상태 → 카드가 빠지고 다음 카드 위에 결과 한 줄 + 다음 카드로 포커스, 주기 갱신은 그대로", async () => {
  let done!: (r: Response) => void;
  POST = () => new Promise(r => { done = r; });
  reload.mockImplementation(async () => { S = state([cand("c_1", { status: "confirmed" }), cand("c_2", { revision: 5 })]); return true; });
  await show(state([cand("c_1"), cand("c_2", { revision: 5 })]), "c_1");
  await click(btn("남기기"));
  expect(posts().map(c => c.body)).toEqual([{ candidate_id: "c_1", action: "confirm", expected_revision: 2 }]);
  expect(stat("c_1")).toBe("저장하고 있어요…");
  expect([...el.querySelectorAll("button")].every(b => b.disabled)).toBe(true);   // 다른 카드도 잠긴다
  await act(async () => done(json(200, {}))); await flush();
  expect(reload).toHaveBeenCalledTimes(1);
  expect(reload).toHaveBeenCalledWith("journal");   // 저장 뒤 다시 받기는 원문을 뺀다
  await redraw();
  expect(location.hash).toBe("#q/review/q1/c_1");   // 주소는 고치지 않는다
  expect(ids()).toEqual(["c_2"]);
  expect(lead("c_2")).toBe("확정한 판단으로 남겼어요.");
  expect(stat("c_2")).toBe("");
  expect(el.querySelector("#save-status")!.textContent).toBe("");
  expect(document.activeElement).toBe(card("c_2"));
  expect(btn("남기기").disabled).toBe(false);
  sentBtn("c_2").focus();
  await show(state([cand("c_2", { revision: 5 })]), "c_1");   // 주기 갱신 — 결과 한 줄과 포커스를 다시 내지 않는다
  expect(document.activeElement).toBe(sentBtn("c_2"));
  expect(posts()).toHaveLength(1);
});

test("결정 뒤 스크롤 — 결과 한 줄이 화면 밖이면 그 줄로 스크롤, 이미 보이면 스크롤하지 않는다, 포커스는 다음 카드", async () => {
  const seen: string[] = [];
  const scroll = vi.fn(function (this: HTMLElement) { seen.push(this.id); });
  Object.defineProperty(HTMLElement.prototype, "scrollIntoView", { value: scroll, configurable: true });
  let top = -33;
  const rect = vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(() => ({ top, bottom: top + 20 } as DOMRect));
  try {
    for (const [t, want] of [[-33, ["lead-c_2"]], [40, []]] as const) {
      top = t; seen.length = 0; reload.mockImplementation(async () => { S = state([cand("c_1", { status: "confirmed" }), cand("c_2")]); return true; });
      await show(state([cand("c_1"), cand("c_2")]), "");
      await click(inCard("c_1", "남기기")); await redraw();
      expect(lead("c_2")).toBe("확정한 판단으로 남겼어요.");
      expect(seen).toEqual(want);
      expect(document.activeElement).toBe(card("c_2"));
      act(() => root.unmount()); root = createRoot(el);
    }
  } finally { rect.mockRestore(); delete (HTMLElement.prototype as { scrollIntoView?: unknown }).scrollIntoView; }
});

test("목록 마지막 카드를 정하면 결과 한 줄은 머리에, 포커스는 머리말로, 앞 카드는 그대로", async () => {
  reload.mockImplementation(async () => { S = state([cand("c_1"), cand("c_2", { status: "excluded", revision: 5 })]); return true; });
  await show(state([cand("c_1"), cand("c_2", { revision: 4 })]), "c_2");
  await click(inCard("c_2", "남기지 않기"));
  expect(posts().at(-1)!.body).toEqual({ candidate_id: "c_2", action: "exclude", expected_revision: 4 });   // 그 카드의 revision(첫 카드 것 아님)
  await redraw();
  expect(ids()).toEqual(["c_1"]);
  expect(el.querySelector("#save-status")!.textContent).toBe("남기지 않음으로 표시했어요.");
  expect(lead("c_1")).toBe("");
  expect(document.activeElement?.id).toBe("review-title");
});

test("문장 눌러 고치기 · 충돌 = 서버 문구 + 고치던 문장 · 실패 = 서버 msg 그대로(잠금 풀림) · 응답 유실 = 성공 여부 불명", async () => {
  await show(state([cand("c_1")]), "c_1");
  await click(sentBtn());
  const ta = el.querySelector("textarea")!;
  expect(document.activeElement).toBe(ta);
  await act(async () => { Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!.call(ta, "고친 문장"); ta.dispatchEvent(new Event("input", { bubbles: true })); });
  POST = () => json(409, { code: "CONFLICT", msg: "다른 곳에서 먼저 바뀌었어요(서버)." });
  reload.mockImplementation(async () => { S = state([cand("c_1", { revision: 3 })]); return true; });
  await click(btn("고친 문장으로 남기기")); await redraw();
  expect(posts().at(-1)!.body).toEqual({ candidate_id: "c_1", action: "edit_confirm", expected_revision: 2, text: "고친 문장" });
  expect(stat()).toBe("다른 곳에서 먼저 바뀌었어요(서버). 고치던 문장은 저장되지 않았어요: 고친 문장");   // 카드가 남으면 그 카드에
  expect(reload.mock.calls.at(-1)).toEqual([undefined]);   // 충돌 = 저장 안 됨, 원문까지 전부 다시 받는다
  expect(btn("남기지 않기")).toBeUndefined();   // 편집 칸이 열린 동안엔 결정 버튼이 없다 — 취소하면 다시 보인다
  await click(btn("취소"));
  POST = () => json(400, { code: "CANDIDATE-REVIEW", msg: "근거가 바뀌었어요." });
  await click(btn("남기지 않기"));
  expect(err()).toBe("근거가 바뀌었어요.");
  expect(btn("남기지 않기").disabled).toBe(false);
  // 응답 유실 — 다른 기기에서 같은 상태로 바뀌었더라도 이 요청의 저장 근거가 아니다
  POST = () => Promise.reject(new TypeError("network"));
  serve((url, m) => (m === "POST" ? POST() : url === "/api/state" ? json(200, state([cand("c_1", { status: "excluded" })])) : json(200, J)));
  reload.mockResolvedValue(true);
  reload.mockClear();
  await click(btn("남기지 않기")); await redraw();
  expect(el.querySelector("[data-candidate-id]")).not.toBeNull();
  expect(err()).toBe("저장 여부를 확인하지 못했어요. 새로 고침해 확인해 주세요.");
  expect(reload).not.toHaveBeenCalled();
  expect(calls.some(c => c.method === "GET" && c.url === "/api/state")).toBe(false);
  serve((url, m) => (m === "POST" ? POST() : url === "/api/state" ? json(200, state([cand("c_1")])) : json(200, J)));
  await show(state([cand("c_1")]), "c_1");
  await click(btn("남기지 않기"));
  expect(err()).toBe("저장 여부를 확인하지 못했어요. 새로 고침해 확인해 주세요.");
});

test("현재 질문의 마지막 확정 뒤에는 범위를 밝히고 전체 확정 판단 목록으로 연결한다", async () => {
  POST = () => json(200, {});
  reload.mockImplementation(async () => { S = state([cand("c_1", { status: "confirmed" })]); return true; });
  await show(state([cand("c_1")]), "c_1");
  await click(btn("남기기")); await redraw();

  expect(el.textContent).toContain("이 질문의 미결 문장 검토가 끝났어요.");
  expect(el.textContent).not.toContain("이번 세션");
  expect(el.textContent).not.toContain("전체 판단을 확정했어요");
  expect([...el.querySelectorAll("a")].map(a => [a.textContent, a.getAttribute("href")])).toContainEqual(["전체 확정 판단 보기", "#structure/cand/confirmed"]);
  expect([...el.querySelectorAll("a.btn")].map(a => [a.textContent, a.getAttribute("href")])).toContainEqual(["질문으로 돌아가기", "#q/q1"]);
});

test("마지막 문장을 수정 확정해도 전체 목록을 이번 판단 결과라고 부르지 않는다", async () => {
  POST = () => json(200, {});
  reload.mockImplementation(async () => { S = state([cand("c_1", { status: "confirmed", text: "수정한 판단" })]); return true; });
  await show(state([cand("c_1")]), "c_1");
  await click(sentBtn());
  const ta = el.querySelector("textarea")!;
  await act(async () => { Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!.call(ta, "수정한 판단"); ta.dispatchEvent(new Event("input", { bubbles: true })); });
  await click(btn("고친 문장으로 남기기")); await redraw();

  expect(el.textContent).toContain("이 질문의 미결 문장 검토가 끝났어요.");
  expect(el.textContent).not.toContain("방금 확정한 판단");
  expect(el.querySelector('a[href="#structure/cand/confirmed"]')?.textContent).toBe("전체 확정 판단 보기");
});

test("마지막 문장을 남기지 않음으로 처리해도 확정 완료로 오인시키지 않는다", async () => {
  POST = () => json(200, {});
  reload.mockImplementation(async () => { S = state([cand("c_1", { status: "excluded" })]); return true; });
  await show(state([cand("c_1")]), "c_1");
  await click(btn("남기지 않기")); await redraw();

  expect(el.textContent).toContain("이 질문의 미결 문장 검토가 끝났어요.");
  expect(el.textContent).not.toContain("확정했어요");
  expect(el.querySelector('a[href="#structure/cand/confirmed"]')?.textContent).toBe("전체 확정 판단 보기");
});

test("옛 end 주소로 와도 남은 문장을 나열하고 완료 안내를 보이지 않는다", async () => {
  await show(state([cand("c_1")]), "end");

  expect(ids()).toEqual(["c_1"]);
  expect(el.textContent).toContain("아직 안 정한 문장 1개");
  expect(el.querySelector('a[href="#structure/cand/confirmed"]')).toBeNull();
  expect(el.textContent).not.toContain("미결 문장 검토가 끝났어요");
});

test("저장 오류는 완료 화면이나 전체 확정 판단 링크로 바뀌지 않는다", async () => {
  POST = () => json(400, { code: "CANDIDATE-REVIEW", msg: "근거가 바뀌었어요." });
  await show(state([cand("c_1")]), "c_1");
  await click(btn("남기지 않기"));

  expect(err()).toBe("근거가 바뀌었어요.");
  expect(el.querySelector("[data-candidate-id]")?.getAttribute("data-candidate-id")).toBe("c_1");
  expect(el.querySelector('a[href="#structure/cand/confirmed"]')).toBeNull();
});

test("질문 ID가 전체 질문 목록에 없으면 완료로 보지 않고 원래 경로로 돌아갈 수 있다", async () => {
  await show(state([]), "end", "q_missing");

  expect(el.textContent).toContain("이 질문을 찾을 수 없어요.");
  expect(el.querySelector('a[href="#q/q1"]')?.textContent).toBe("질문으로 돌아가기");
  expect(el.querySelector('a[href="#structure/cand/confirmed"]')).toBeNull();
  expect(el.textContent).not.toContain("검토가 끝났어요");
});

test("질문 목록 읽기에 실패하면 질문 부재나 완료로 추정하지 않는다", async () => {
  await show(state([], { read: { questions: { ok: false, error: { code: "OFFLINE", msg: "" } } } }), "end");

  expect(el.querySelector(".partfail")).toBeTruthy();
  expect(el.textContent).toContain("질문 목록을 읽지 못했어요");
  expect(el.querySelector('a[href="#q/q1"]')?.textContent).toBe("질문으로 돌아가기");
  expect(el.querySelector('a[href="#structure/cand/confirmed"]')).toBeNull();
  expect(el.textContent).not.toContain("검토가 끝났어요");
});

test("기록 ID가 전체 목록에 없으면 완료로 보지 않고 원래 경로로 돌아갈 수 있다", async () => {
  await show(state([]), "end", "r:r_missing");

  expect(el.textContent).toContain("이 기록을 찾을 수 없어요.");
  expect(el.querySelector('a[href="#q/q1"]')?.textContent).toBe("질문으로 돌아가기");
  expect(el.querySelector('a[href="#structure/cand/confirmed"]')).toBeNull();
  expect(el.textContent).not.toContain("검토가 끝났어요");
});

test("기록 목록의 다음 페이지가 남아 있으면 현재 기록 부재를 완료로 취급하지 않는다", async () => {
  await show(state([], { journal_next_before: "opaque-cursor" }), "end", "r:r_missing");

  expect(el.textContent).toContain("이 기록이 현재 목록에 없어 검토가 끝났는지 확인하지 못했어요.");
  expect(el.querySelector('a[href="#q/q1"]')?.textContent).toBe("질문으로 돌아가기");
  expect(el.querySelector('a[href="#structure/cand/confirmed"]')).toBeNull();
  expect(el.textContent).not.toContain("검토가 끝났어요.");
});

test("기록 목록 읽기에 실패하면 기록 부재나 완료로 추정하지 않는다", async () => {
  await show(state([], { read: { journal: { ok: false, error: { code: "OFFLINE", msg: "" } } } }), "end", "r:r_missing");

  expect(el.querySelector(".partfail")).toBeTruthy();
  expect(el.textContent).toContain("내 글 목록을 읽지 못했어요");
  expect(el.querySelector('a[href="#q/q1"]')?.textContent).toBe("질문으로 돌아가기");
  expect(el.querySelector('a[href="#structure/cand/confirmed"]')).toBeNull();
  expect(el.textContent).not.toContain("검토가 끝났어요");
});


// 미저장 보호 — 고친 문장이 원래 문장과 다르고 저장 전이면 이 주소를 껍데기에 알린다(setDirty). 취소·저장 성공·화면을 떠날 때 푼다
const typeIn = (ta: HTMLTextAreaElement, v: string) => act(async () => {
  Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!.call(ta, v); ta.dispatchEvent(new Event("input", { bubbles: true })); });

test("미저장 보호 — 고치면 주소 등록 · 원래 문장으로 되돌리거나 취소하면 해제 · 화면을 떠나면 해제", async () => {
  await show(state([cand("c_1")]), "c_1");
  await click(sentBtn());
  expect(setDirty).not.toHaveBeenCalledWith("#q/review/q1/c_1");   // 열기만 = 고친 것 아님
  const ta = el.querySelector("textarea")!;
  await typeIn(ta, "고친 문장");
  expect(setDirty).toHaveBeenLastCalledWith("#q/review/q1/c_1");
  await typeIn(ta, "담당을 먼저 정한다 c_1");   // 원래 문장 그대로
  expect(setDirty).toHaveBeenLastCalledWith(null);
  await typeIn(ta, "다시 고침");
  expect(setDirty).toHaveBeenLastCalledWith("#q/review/q1/c_1");
  await click(btn("취소"));
  expect(setDirty).toHaveBeenLastCalledWith(null);
  await click(sentBtn());
  await typeIn(el.querySelector("textarea")!, "떠나기 전");
  expect(setDirty).toHaveBeenLastCalledWith("#q/review/q1/c_1");
  act(() => root.unmount());
  expect(setDirty).toHaveBeenLastCalledWith(null);
  root = createRoot(el);
});

test("미저장 보호 — 저장 실패면 그대로 · 저장 성공이면 다시 받기 전에 해제(다시 받기 실패로 카드가 남아도)", async () => {
  await show(state([cand("c_1")]), "c_1");
  await click(sentBtn());
  await typeIn(el.querySelector("textarea")!, "고친 문장");
  POST = () => json(400, { code: "CANDIDATE-REVIEW", msg: "근거가 바뀌었어요." });
  await click(btn("고친 문장으로 남기기"));
  expect(setDirty).toHaveBeenLastCalledWith("#q/review/q1/c_1");
  POST = () => json(200, {});
  reload.mockResolvedValue(false);   // 상태를 다시 받지 못함 — 카드는 그대로 남는다
  await click(btn("고친 문장으로 남기기"));
  expect(el.querySelector("[data-candidate-id]")).not.toBeNull();
  expect(setDirty).toHaveBeenLastCalledWith(null);
  const nulls = setDirty.mock.calls.map((a, i) => (a[0] === null ? i : -1)).filter(i => i >= 0);
  const cleared = setDirty.mock.invocationCallOrder[nulls[nulls.length - 1]];
  expect(cleared).toBeLessThan(reload.mock.invocationCallOrder.at(-1)!);
  // 저장한 문장이 새 기준 — 같은 칸에 다시 고치면 다시 등록, 저장한 문장으로 되돌리면 해제
  await typeIn(el.querySelector("textarea")!, "저장 뒤 또 고침");
  expect(setDirty).toHaveBeenLastCalledWith("#q/review/q1/c_1");
  await typeIn(el.querySelector("textarea")!, "고친 문장");
  expect(setDirty).toHaveBeenLastCalledWith(null);
});

test("미저장 보호 — 동시에 고친 카드 둘: 하나를 풀어도 다른 카드의 등록은 남는다 · 모두 깨끗할 때만 해제", async () => {
  const ctx = { reload, setDirty };
  function Two() {
    const mark = useDirtyCards(ctx);
    const one = (id: string) => (
      <div id={"box-" + id}><Card S={state([])} c={cand(id) as never} n={1} w={WORDS} locked={false}
        lead="" status="" err="" onDecide={() => {}} onDirty={d => mark(id, d)} /></div>);
    return <>{one("c_1")}{one("c_2")}</>;
  }
  await act(async () => root.render(<QueryClientProvider client={queryClient}><Two /></QueryClientProvider>));
  await flush(); await flush();
  const box = (id: string) => el.querySelector("#box-" + id)!;
  const inBox = (id: string, t: string) => [...box(id).querySelectorAll("button")].find(b => b.textContent === t) as HTMLButtonElement;
  history.replaceState(null, "", "#q/review/q1/c_1");
  const sentIn = (id: string) => box(id).querySelector("button[title='눌러서 고치기']") as HTMLButtonElement;
  await click(sentIn("c_1")); await typeIn(box("c_1").querySelector("textarea")!, "하나");
  expect(setDirty).toHaveBeenLastCalledWith("#q/review/q1/c_1");
  history.replaceState(null, "", "#q/review/q1/c_2");
  await click(sentIn("c_2")); await typeIn(box("c_2").querySelector("textarea")!, "둘");
  await click(inBox("c_1", "취소"));
  expect(setDirty).toHaveBeenLastCalledWith("#q/review/q1/c_2");   // c_1 을 풀어도 c_2 는 남는다
  expect(setDirty).not.toHaveBeenLastCalledWith(null);
  await click(inBox("c_2", "취소"));
  expect(setDirty).toHaveBeenLastCalledWith(null);
});

test("미저장 보호 — 나열 화면에서 두 카드를 같이 고쳐도 카드마다 등록, 한 카드의 저장은 다른 카드의 초안과 등록을 건드리지 않는다", async () => {
  reload.mockImplementation(async () => { S = state([cand("c_1", { status: "confirmed", text: "하나", revision: 4 }), cand("c_2", { revision: 6 })]); return true; });
  await show(state([cand("c_1"), cand("c_2", { revision: 6 })]), "c_1");
  await click(sentBtn("c_1")); await typeIn(card("c_1").querySelector("textarea")!, "하나");
  await click(sentBtn("c_2")); await typeIn(card("c_2").querySelector("textarea")!, "둘");
  expect(setDirty).toHaveBeenLastCalledWith("#q/review/q1/c_1");
  await click(inCard("c_1", "고친 문장으로 남기기"));
  expect(posts().at(-1)!.body).toEqual({ candidate_id: "c_1", action: "edit_confirm", expected_revision: 2, text: "하나" });
  await redraw();
  expect(ids()).toEqual(["c_2"]);
  expect(lead("c_2")).toBe("고친 문장을 확정한 판단으로 남겼어요.");
  expect(card("c_2").querySelector("textarea")!.value).toBe("둘");
  expect(setDirty).toHaveBeenLastCalledWith("#q/review/q1/c_1");   // c_2 는 아직 고친 채 — 등록이 남는다
  expect(setDirty).not.toHaveBeenLastCalledWith(null);
  await click(inCard("c_2", "취소"));
  expect(setDirty).toHaveBeenLastCalledWith(null);
});

test("문장 눌러 고치기 — 문장은 버튼(Enter, Space), 편집 칸은 문장 바로 아래, Esc = 취소(요청 0, 해제) + 문장으로 포커스, 저장 중엔 Esc 도 잠김", async () => {
  await show(state([cand("c_1")]), "c_1");
  const b = sentBtn();
  expect([b.tagName, b.type]).toEqual(["BUTTON", "button"]);
  expect(b.getAttribute("aria-controls")).toBe("rvedit-c_1");
  expect((el.querySelector("#rvedit-c_1") as HTMLFormElement).hidden).toBe(true);
  await click(b);
  expect((el.querySelector("#rvedit-c_1") as HTMLFormElement).hidden).toBe(false);
  expect(card("c_1").querySelector("[data-candidate-id]")!.contains(el.querySelector("#rvedit-c_1"))).toBe(true);
  expect(sentBtn()).toBeNull();   // 열린 동안 문장은 글로만(최신 문장이 보인다)
  expect([...el.querySelectorAll("#rvedit-c_1 button")].map(x => x.textContent)).toEqual(["고친 문장으로 남기기", "취소"]);
  const ta = el.querySelector("#rvtext-c_1") as HTMLTextAreaElement;
  await typeIn(ta, "고치다 만 문장");
  expect(setDirty).toHaveBeenLastCalledWith("#q/review/q1/c_1");
  await act(async () => { ta.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true })); });
  expect((el.querySelector("#rvedit-c_1") as HTMLFormElement).hidden).toBe(true);
  expect(setDirty).toHaveBeenLastCalledWith(null);
  expect(document.activeElement).toBe(sentBtn());
  expect(posts()).toEqual([]);
  let done!: (r: Response) => void;
  POST = () => new Promise(r => { done = r; });
  await click(sentBtn()); await typeIn(el.querySelector("#rvtext-c_1") as HTMLTextAreaElement, "저장 중");
  await click(btn("고친 문장으로 남기기"));
  await act(async () => { el.querySelector("#rvtext-c_1")!.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true })); });
  expect((el.querySelector("#rvedit-c_1") as HTMLFormElement).hidden).toBe(false);
  await act(async () => done(json(400, { code: "X", msg: "안 됐어요." }))); await flush();
  expect(err()).toBe("안 됐어요.");
});

test("편집 칸이 열린 동안엔 그 카드의 [남기기] [남기지 않기]를 숨긴다: 보이는 버튼은 편집 칸의 둘뿐, 취소하면 다시 보인다, 다른 카드는 그대로, 등록은 취소하거나 떠날 때까지 남는다", async () => {
  const shown = (id: string) => [...card(id).querySelectorAll("button")].filter(b => !b.closest("[hidden]")).map(b => b.textContent);
  await show(state([cand("c_1"), cand("c_2", { revision: 9 })]), "c_1");
  expect(shown("c_1")).toEqual(["담당을 먼저 정한다 c_1", "남기기", "남기지 않기"]);
  await click(sentBtn());
  await typeIn(card("c_1").querySelector("textarea")!, "고친 문장");
  expect(setDirty).toHaveBeenLastCalledWith("#q/review/q1/c_1");
  expect(shown("c_1")).toEqual(["고친 문장으로 남기기", "취소"]);
  expect([...card("c_1").querySelectorAll("button")].map(b => b.textContent)).toEqual(["고친 문장으로 남기기", "취소"]);   // 숨긴 결정 버튼은 그리지 않는다
  expect(shown("c_2")).toEqual(["담당을 먼저 정한다 c_2", "남기기", "남기지 않기"]);
  expect(inCard("c_2", "남기기").disabled).toBe(false);
  const kids = [...card("c_1").querySelector("[data-candidate-id]")!.children].map(x => x.tagName + (x.classList.contains("labels") ? ".labels" : ""));
  expect(kids.indexOf("DIV.labels")).toBeLessThan(kids.indexOf("FORM"));   // 쓴 쪽 표시는 문장 바로 아래, 편집 칸은 그 다음
  expect(kids.slice(1, 3)).toEqual(["P", "DIV.labels"]);
  await click(inCard("c_1", "취소"));
  expect(setDirty).toHaveBeenLastCalledWith(null);
  expect(shown("c_1")).toEqual(["담당을 먼저 정한다 c_1", "남기기", "남기지 않기"]);
  await click(sentBtn());
  expect(card("c_1").querySelector("textarea")!.value).toBe("담당을 먼저 정한다 c_1");
  await typeIn(card("c_1").querySelector("textarea")!, "또 고친 문장");
  setDirty.mockClear();
  await click(inCard("c_2", "남기지 않기"));   // 다른 카드의 결정은 이 카드의 초안과 등록을 건드리지 않는다
  expect(posts().at(-1)!.body).toMatchObject({ candidate_id: "c_2", action: "exclude", expected_revision: 9 });
  expect(setDirty).not.toHaveBeenCalledWith(null);
  expect(card("c_1").querySelector("textarea")!.value).toBe("또 고친 문장");
  act(() => root.unmount());   // 화면을 떠나면 해제
  expect(setDirty).toHaveBeenLastCalledWith(null);
  root = createRoot(el);
});

test("고친 문장 저장 응답 유실 — 다시 읽은 상태가 바뀌었고 같은 문장이어도 이 요청의 저장 증거가 아니다: 저장 알림·해제·다시 받기·이동 없이 고치던 문장과 불확실 문구를 남긴다", async () => {
  await show(state([cand("c_1")]), "c_1");
  await click(sentBtn());
  await typeIn(el.querySelector("textarea")!, "고친 문장");
  expect(setDirty).toHaveBeenLastCalledWith("#q/review/q1/c_1");
  POST = () => Promise.reject(new TypeError("network"));
  // 다른 기기에서 같은 문장으로 확정했을 수도 있다 — 상태·문장·revision 이 맞아도 이 요청과 이어 줄 근거가 없다
  serve((url, m) => (m === "POST" ? POST() : url === "/api/state" ? json(200, state([cand("c_1", { status: "confirmed", text: "고친 문장", revision: 3 })])) : json(200, J)));
  setDirty.mockClear();
  await click(btn("고친 문장으로 남기기")); await flush();
  expect(posts().at(-1)!.body).toMatchObject({ action: "edit_confirm", text: "고친 문장" });
  expect(reload).not.toHaveBeenCalled();
  expect(calls.some(c => c.method === "GET" && c.url === "/api/state")).toBe(false);
  expect(location.hash).toBe("#q/review/q1/c_1");
  expect(setDirty).not.toHaveBeenCalledWith(null);
  expect(el.querySelector("[data-candidate-id]")!.getAttribute("data-candidate-id")).toBe("c_1");
  expect(el.querySelector("textarea")!.value).toBe("고친 문장");
  expect(stat()).not.toContain("남겼어요");
  expect(err()).toBe("저장 여부를 확인하지 못했어요. 새로 고침해 확인해 주세요.");
  expect(btn("고친 문장으로 남기기").disabled).toBe(false);   // 잠금은 풀린다
  // 기준은 원래 문장 그대로 — 원래 문장으로 되돌리면 해제, 다시 고치면 등록
  await typeIn(el.querySelector("textarea")!, "담당을 먼저 정한다 c_1");
  expect(setDirty).toHaveBeenLastCalledWith(null);
  await typeIn(el.querySelector("textarea")!, "고친 문장");
  expect(setDirty).toHaveBeenLastCalledWith("#q/review/q1/c_1");
  act(() => root.unmount());   // 떠날 때만 해제
  expect(setDirty).toHaveBeenLastCalledWith(null);
  root = createRoot(el);
});

test("더티 편집 중 같은 후보의 원격 갱신은 초안을 보존하고 편집 시작 revision으로 충돌 검사를 한다", async () => {
  await show(state([cand("c_1", { revision: 2 })]), "c_1");
  await click(sentBtn());
  await typeIn(el.querySelector("textarea")!, "내 초안");

  await show(state([cand("c_1", { text: "서버 최신 문장", revision: 3 })]), "c_1");
  expect(el.querySelector("textarea")!.value).toBe("내 초안");
  expect(el.querySelector("[data-candidate-id]")!.textContent).toContain("서버 최신 문장");

  await click(btn("고친 문장으로 남기기"));
  expect(posts().at(-1)!.body).toEqual({ candidate_id: "c_1", action: "edit_confirm", expected_revision: 2, text: "내 초안" });
});

test("깨끗한 편집 화면은 같은 후보의 원격 문장과 revision을 받아들인 뒤 그 revision으로 저장한다", async () => {
  await show(state([cand("c_1", { revision: 2 })]), "c_1");
  await show(state([cand("c_1", { text: "서버 최신 문장", revision: 3 })]), "c_1");
  expect(el.querySelector("textarea")!.value).toBe("서버 최신 문장");

  await click(sentBtn());
  await typeIn(el.querySelector("textarea")!, "최신 문장에서 시작한 초안");
  await click(btn("고친 문장으로 남기기"));
  expect(posts().at(-1)!.body).toEqual({ candidate_id: "c_1", action: "edit_confirm", expected_revision: 3, text: "최신 문장에서 시작한 초안" });
});

test("원격 변경 뒤 초안을 기준 문장으로 되돌리면 최신 원격 문장과 revision으로 동기화한다", async () => {
  await show(state([cand("c_1", { revision: 2 })]), "c_1");
  await click(sentBtn());
  await typeIn(el.querySelector("textarea")!, "내 초안");

  await show(state([cand("c_1", { text: "서버 최신 문장", revision: 3 })]), "c_1");
  await typeIn(el.querySelector("textarea")!, "담당을 먼저 정한다 c_1");
  expect(el.querySelector("textarea")!.value).toBe("서버 최신 문장");

  await typeIn(el.querySelector("textarea")!, "최신 문장에서 시작한 초안");
  await click(btn("고친 문장으로 남기기"));
  expect(posts().at(-1)!.body).toEqual({ candidate_id: "c_1", action: "edit_confirm", expected_revision: 3, text: "최신 문장에서 시작한 초안" });
});

test.each([
  ["confirm", "excluded", "남기기"],
  ["confirm", "confirmed", "남기기"],
  ["exclude", "confirmed", "남기지 않기"],
  ["exclude", "excluded", "남기지 않기"],
] as const)("OFFLINE %s 요청에서 원격 상태가 %s이면 저장 성공으로 단정하지 않는다", async (action, remoteStatus, button) => {
  await show(state([cand("c_1")]), "c_1");
  POST = () => Promise.reject(new TypeError("network"));
  serve((url, m) => m === "POST" ? POST()
    : url === "/api/state" ? json(200, state([cand("c_1", { status: remoteStatus })]))
      : url.startsWith("/api/journal") ? json(200, J) : json(404, {}));

  await click(btn(button));

  expect(posts().at(-1)!.body).toMatchObject({ candidate_id: "c_1", action });
  expect(reload).not.toHaveBeenCalled();
  expect(calls.some(c => c.method === "GET" && c.url === "/api/state")).toBe(false);
  expect(el.querySelector("[data-candidate-id]")).not.toBeNull();
  expect(err()).toBe("저장 여부를 확인하지 못했어요. 새로 고침해 확인해 주세요.");
  expect(stat()).not.toContain("남겼어요");
});

test("결정마다 그 카드의 revision 을 보낸다: 남기기, 남기지 않기, 고친 문장으로 남기기 모두 첫 카드가 아닌 카드에서도", async () => {
  POST = () => json(200, {});
  reload.mockResolvedValue(false);   // 다시 받지 못함 — 카드가 그대로 남아 이어서 누를 수 있다
  await show(state([cand("c_1", { revision: 2 }), cand("c_2", { revision: 7 }), cand("c_3", { revision: 11 })]), "c_1");
  await click(inCard("c_2", "남기지 않기"));
  expect(posts().at(-1)!.body).toEqual({ candidate_id: "c_2", action: "exclude", expected_revision: 7 });
  await click(inCard("c_3", "남기기"));
  expect(posts().at(-1)!.body).toEqual({ candidate_id: "c_3", action: "confirm", expected_revision: 11 });
  await click(sentBtn("c_2")); await typeIn(card("c_2").querySelector("textarea")!, "둘 고침");
  await click(inCard("c_2", "고친 문장으로 남기기"));
  expect(posts().at(-1)!.body).toEqual({ candidate_id: "c_2", action: "edit_confirm", expected_revision: 7, text: "둘 고침" });
  await click(inCard("c_1", "남기기"));
  expect(posts().at(-1)!.body).toEqual({ candidate_id: "c_1", action: "confirm", expected_revision: 2 });
  expect(posts()).toHaveLength(4);
});

test("저장 중 잠금은 요청이 끝날 때까지: 저장 중에 새 상태(표지 갱신)가 와도 다른 카드는 꺼져 있다, 충돌 뒤 다시 받기에 실패해도 풀린다", async () => {
  let done!: (r: Response) => void;
  POST = () => new Promise(r => { done = r; });
  reload.mockImplementation(async () => { S = state([cand("c_1", { status: "confirmed" }), cand("c_2", { revision: 5 })]); return true; });
  await show(state([cand("c_1"), cand("c_2", { revision: 5 })]), "c_1");
  await click(inCard("c_1", "남기기"));
  await show(state([cand("c_1"), cand("c_2", { revision: 5 })]), "c_1");   // 요청이 가는 중에 표지 갱신이 새 상태 객체를 가져왔다
  const offs = () => [inCard("c_2", "남기기"), inCard("c_2", "남기지 않기"), sentBtn("c_2")].map(b => b.disabled);
  expect(offs()).toEqual([true, true, true]);
  expect(inCard("c_1", "남기기").disabled).toBe(true);
  await act(async () => done(json(200, {}))); await flush();
  await redraw();
  expect(ids()).toEqual(["c_2"]);
  expect(lead("c_2")).toBe("확정한 판단으로 남겼어요.");
  expect(offs()).toEqual([false, false, false]);
  reload.mockResolvedValue(false);   // 충돌 뒤 다시 받기 실패
  await click(inCard("c_2", "남기지 않기"));
  await show(state([cand("c_2", { revision: 6 })]), "c_1");
  expect(offs()).toEqual([true, true, true]);
  await act(async () => done(json(409, { code: "CONFLICT", msg: "다른 곳에서 먼저 바뀌었어요(서버)." }))); await flush();
  expect(stat("c_2")).toBe("다른 곳에서 먼저 바뀌었어요(서버).");
  expect(offs()).toEqual([false, false, false]);
});

// 껍데기의 실제 reload 와 상태 조회(useAppState)를 그대로 쓴다 — 가짜 서버의 요청 기록으로 무엇을 다시 받았는지 센다
test("결정 뒤에는 상태만 다시 받고 남은 카드의 근거 원문은 다시 받지 않는다: 들어올 때 글마다 한 번, 새로 고침(전체 다시 받기)은 원문도 다시", async () => {
  let srv = state([cand("c_1"), cand("c_2", { record_id: "r2", revision: 5 }), cand("c_3", { record_id: "r3", revision: 8 })]);
  serve((url, m) => (m === "POST" ? json(200, {}) : url === "/api/state" ? json(200, srv)
    : url.startsWith("/api/journal?id=") ? json(200, { ...J, id: url.split("=")[1] }) : json(404, {})));
  const R = SCREENS.review;
  function Host() {
    const st = useAppState().S;
    return st ? <R ctx={{ reload: appReload, setDirty, state: st, args: ["q", "q1", "", "#q/q1", "질문으로 돌아가기"] }} /> : null;
  }
  history.replaceState(null, "", "#q/review/q1/");
  await act(async () => root.render(<QueryClientProvider client={queryClient}><Host /></QueryClientProvider>));
  for (let i = 0; i < 4; i++) await flush();
  const stateGets = () => calls.filter(c => c.method === "GET" && c.url === "/api/state").length;
  const journalGets = () => calls.filter(c => c.method === "GET" && c.url.startsWith("/api/journal")).map(c => c.url).sort();
  expect(ids()).toEqual(["c_1", "c_2", "c_3"]);
  expect(stateGets()).toBe(1);
  expect(journalGets()).toEqual(["/api/journal?id=r1", "/api/journal?id=r2", "/api/journal?id=r3"]);   // 글마다 한 번
  srv = state([cand("c_1", { status: "confirmed", revision: 3 }), cand("c_2", { record_id: "r2", revision: 5 }), cand("c_3", { record_id: "r3", revision: 8 })]);
  await click(inCard("c_1", "남기기"));
  for (let i = 0; i < 3; i++) await flush();
  expect(posts().map(c => c.body)).toEqual([{ candidate_id: "c_1", action: "confirm", expected_revision: 2 }]);
  expect(stateGets()).toBe(2);   // 상태는 다시 받는다
  expect(journalGets()).toEqual(["/api/journal?id=r1", "/api/journal?id=r2", "/api/journal?id=r3"]);   // 원문은 다시 받지 않는다
  expect(ids()).toEqual(["c_2", "c_3"]);
  expect(lead("c_2")).toBe("확정한 판단으로 남겼어요.");
  expect(inCard("c_2", "남기기").disabled).toBe(false);
  await act(async () => { await reloadState(); });   // 머리글 새로 고침 = 떠 있는 조회 전부(남은 카드의 원문 포함)
  for (let i = 0; i < 3; i++) await flush();
  expect(stateGets()).toBe(3);
  expect(journalGets()).toEqual(["/api/journal?id=r1", "/api/journal?id=r2", "/api/journal?id=r2", "/api/journal?id=r3", "/api/journal?id=r3"]);
});
