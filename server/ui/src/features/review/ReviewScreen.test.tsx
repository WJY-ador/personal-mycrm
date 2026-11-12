// 판단 검토(원문과 대조하기) — 옛 app.html renderReview·decide 동작을 옮긴 시험(R3). 껍데기 라우터 대신 주소(history)와 ctx(상태·args)를 직접 넘긴다.
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
// 껍데기 흉내 — 주소가 바뀌면(replace·링크) 그 조각으로 다시 그린다. jsdom 의 주소 바꾸기는 다음 작업에서 끝나 바뀔 때까지 기다린다
const at = () => decodeURIComponent(location.hash.slice(1)).split("/");
async function follow() {
  for (let i = 0; i < 20 && at()[3] === args[2]; i++) await act(async () => { await new Promise(r => setTimeout(r, 5)); });
  await show(S, at()[3] || "", at()[2]);
}
const redraw = () => show(S, args[2], args[1]);   // 껍데기 render() — reload 가 받은 새 상태로 다시 그린다
const landed = async (h: string) => { for (let i = 0; i < 20 && location.hash !== h; i++) await act(async () => { await new Promise(r => setTimeout(r, 5)); }); return location.hash; };
const btn = (t: string) => [...el.querySelectorAll("button")].find(b => b.textContent === t) as HTMLButtonElement;
const posts = () => calls.filter(c => c.method === "POST");

let POST: () => Response | Promise<Response> = () => json(200, {});
beforeEach(() => {
  installFetch(); queryClient.clear(); reload.mockReset(); reload.mockResolvedValue(true); setDirty.mockReset();
  POST = () => json(200, {});
  serve((url, m) => (m === "POST" ? POST() : url.startsWith("/api/journal") ? json(200, J) : json(404, {})));
  el = document.createElement("div"); document.body.append(el); root = createRoot(el);
});
afterEach(() => { act(() => root.unmount()); el.remove(); vi.unstubAllGlobals(); });

test("한 장 — 질문·문장·칩·재검토 0 · 근거 원문(구절 문단 ±1 흐림·mark·전체 원문·기술 정보) · 원문 확인 뒤에만 결정 버튼", async () => {
  serve((_u, m) => (m === "POST" ? POST() : new Promise(() => {})));   // 원문을 아직 못 받음
  await show(state([cand("c_1"), cand("c_2")]), "c_1");
  expect(el.querySelector("h2")!.textContent).toBe("원문과 대조하기");
  expect(el.textContent).toContain("아직 안 정한 문장 2개");
  expect(el.querySelector("a.link")!.getAttribute("href")).toBe("#q/q1");
  expect(el.querySelector("[data-candidate-id]")!.textContent).toContain("질문: 도입 순서는?");
  expect([...el.querySelectorAll(".labels > *")].map(x => x.textContent)).toEqual(["AI가 쓴 문장"]);   // AI 표시 하나(디자인 2 C3)
  expect(el.querySelector(".recheck")).toBeNull();
  expect(["남기기", "고쳐서 남기기", "반영 안 함"].map(t => btn(t).disabled)).toEqual([true, true, true]);
  expect(el.textContent).toContain("원문을 불러오는 중이에요…");
  serve(() => json(200, J)); queryClient.clear();
  await show(state([cand("c_1"), cand("c_2")]), "c_1");
  expect(["남기기", "고쳐서 남기기", "반영 안 함"].map(t => btn(t).disabled)).toEqual([false, false, false]);
  const src = el.querySelector("#rvsrc")!;
  expect(src.querySelector("h3")!.textContent).toBe("근거 원문: 도입 회고");
  const ex = src.querySelector(":scope > .doc")!;
  expect([...ex.querySelectorAll("p")].map(p => [p.className, p.textContent])).toEqual([
    ["dim", "첫 문단이다."], ["", "고객은 입력 담당을 먼저 정했다. 그게 맞았다."], ["dim", "셋째 문단."]]);
  expect(ex.querySelector("mark")!.textContent).toBe("입력 담당을 먼저");
  expect(src.querySelector("details.fold summary")!.textContent).toBe("전체 원문 보기");
  expect(src.querySelector("details.tech")!.textContent).toContain("출처 회고 메모(파일), 쓸 당시 표기 파일에서 가져옴, 근거 구절 9자");
  expect(btn("이전 문장").disabled).toBe(true);
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
  expect(el.querySelector("#rvsrc")!.textContent).toContain("이 판단의 근거 구절이 저장된 원문과 일치하지 않아 남길 수 없어요. 찾던 구절: 없는 구절");
  expect(btn("남기기").disabled).toBe(true);
  queryClient.clear(); serve(() => json(404, { code: "RECORD-MISSING", msg: "없음" }));
  await show(state([cand("c_1")]), "c_1");
  expect(el.querySelector("#rvsrc")!.textContent).toContain("원문을 불러오지 못했어요. 근거를 확인할 수 없어 남길 수 없어요. 새로 고침해도 그대로면 다시 로그인해 보세요.");
  expect(el.querySelector("#rvsrc code")!.textContent).toBe("RECORD-MISSING");
  expect(btn("남기기").disabled).toBe(true);
  queryClient.clear(); serve(() => json(200, J));
  await show(state([cand("c_1", { quote: "다.\n\n고객은", review: "external" })]), "c_1");
  expect(el.querySelector("#rvsrc")!.textContent).toContain("근거 구절이 문단 경계에 걸쳐 있어 위치를 강조하지 못했어요.");
  expect(btn("남기기").disabled).toBe(false);
  expect(el.querySelector(".recheck")!.textContent).toContain("근거 글이 남이 쓴 글이라 이 판단을 확정할 수 없어요.");
});

test("주소 바꿔 끼우기 — 빈 자리·옛 숫자 = 그 자리 판단 · 넘친 숫자 = 목록 끝 · 정한 판단 = 남은 첫 판단 · 끝 화면 · 빈 목록", async () => {
  const st = state([cand("c_1"), cand("c_2"), cand("c_x", { question_id: "q2" })]);
  await show(st, ""); expect(await landed("#q/review/q1/c_1")).toBe("#q/review/q1/c_1");
  await show(st, "1"); expect(await landed("#q/review/q1/c_2")).toBe("#q/review/q1/c_2");
  await show(st, "9"); expect(await landed("#q/review/q1/end")).toBe("#q/review/q1/end");
  await follow();
  expect(el.textContent).toContain("목록 끝이에요. 아직 안 정한 문장 2개가 남아 있어요.");
  expect([...el.querySelectorAll("a.btn")].map(a => [a.textContent, a.getAttribute("href")])).toEqual([["남은 문장 보기", "#q/review/q1/c_1"], ["질문으로 돌아가기", "#q/q1"]]);
  await show(st, "c_gone"); expect(await landed("#q/review/q1/c_1")).toBe("#q/review/q1/c_1");
  await show(state([]), "c_1");
  expect(el.textContent).toContain("아직 안 정한 문장이 없어요.이 질문의 미결 문장 검토가 끝났어요.새 글에서 판단을 뽑으면 여기에 떠요.");
  await show(state([cand("c_9", { question_id: null })]), "c_9", "r:r1");
  expect(el.querySelector("[data-candidate-id]")!.textContent).toContain("질문 없음, 내 글: 도입 회고");
  expect(el.querySelector("#decision-help")!.textContent).toBe("남기면 확정한 판단에 들어가고(질문 없음), 반영 안 함으로 둬도 판단 문장과 원문은 삭제되지 않아요.");
  await show(state([], { read: { candidates: { ok: false, error: { code: "OFFLINE", msg: "x" } } } }), "c_1");
  expect(el.querySelector(".partfail")!.textContent).toContain("문장 목록을 읽지 못했어요. 나머지는 정상이에요.서버에 연결하지 못했어요.");
});

test("남기기 — 호출 하나(expected_revision) · 저장 중 잠금 · 새 상태 → 다음 판단 + 결과 한 줄(한 번) · 머리말로 초점", async () => {
  let done!: (r: Response) => void;
  POST = () => new Promise(r => { done = r; });
  reload.mockImplementation(async () => { S = state([cand("c_1", { status: "confirmed" }), cand("c_2")]); return true; });
  await show(state([cand("c_1"), cand("c_2")]), "c_1");
  await click(btn("남기기"));
  expect(posts().map(c => c.body)).toEqual([{ candidate_id: "c_1", action: "confirm", expected_revision: 2 }]);
  expect(el.querySelector("#save-status")!.textContent).toBe("저장하고 있어요…");
  expect([...el.querySelectorAll("button")].every(b => b.disabled)).toBe(true);
  await act(async () => done(json(200, {}))); await flush();
  expect(reload).toHaveBeenCalledTimes(1);
  await redraw();
  expect(await landed("#q/review/q1/c_2")).toBe("#q/review/q1/c_2");
  await follow();
  expect(el.querySelector("[data-candidate-id]")!.getAttribute("data-candidate-id")).toBe("c_2");
  expect(el.querySelector("#save-status")!.textContent).toBe("확정한 판단으로 남겼어요.");
  expect(document.activeElement?.id).toBe("review-title");
  expect(btn("남기기").disabled).toBe(false);
  await click(btn("건너뛰기")); await follow();
  expect(el.textContent).toContain("목록 끝이에요");
  expect(el.querySelector("#save-status")!.textContent).toBe("");
});

test("고쳐서 남기기 · 충돌 = 서버 문구 + 고치던 문장 · 실패 = 서버 msg 그대로(잠금 풀림) · 응답 유실 = 성공 여부 불명", async () => {
  await show(state([cand("c_1")]), "c_1");
  await click(btn("고쳐서 남기기"));
  const ta = el.querySelector("textarea")!;
  expect(document.activeElement).toBe(ta);
  await act(async () => { Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!.call(ta, "고친 문장"); ta.dispatchEvent(new Event("input", { bubbles: true })); });
  POST = () => json(409, { code: "CONFLICT", msg: "다른 곳에서 먼저 바뀌었어요(서버)." });
  reload.mockImplementation(async () => { S = state([cand("c_1", { revision: 3 })]); return true; });
  await click(btn("고친 문장으로 남기기")); await redraw();
  expect(posts().at(-1)!.body).toEqual({ candidate_id: "c_1", action: "edit_confirm", expected_revision: 2, text: "고친 문장" });
  expect(el.querySelector("#save-status")!.textContent).toBe("다른 곳에서 먼저 바뀌었어요(서버). 고치던 문장은 저장되지 않았어요: 고친 문장");
  POST = () => json(400, { code: "CANDIDATE-REVIEW", msg: "근거가 바뀌었어요." });
  await click(btn("반영 안 함"));
  expect(el.querySelector("#save-error")!.textContent).toBe("근거가 바뀌었어요.");
  expect(btn("반영 안 함").disabled).toBe(false);
  // 응답 유실 — 다른 기기에서 같은 상태로 바뀌었더라도 이 요청의 저장 근거가 아니다
  POST = () => Promise.reject(new TypeError("network"));
  serve((url, m) => (m === "POST" ? POST() : url === "/api/state" ? json(200, state([cand("c_1", { status: "excluded" })])) : json(200, J)));
  reload.mockResolvedValue(true);
  reload.mockClear();
  await click(btn("반영 안 함")); await redraw();
  expect(el.querySelector("[data-candidate-id]")).not.toBeNull();
  expect(el.querySelector("#save-error")!.textContent).toBe("저장 여부를 확인하지 못했어요. 새로 고침해 확인해 주세요.");
  expect(reload).not.toHaveBeenCalled();
  expect(calls.some(c => c.method === "GET" && c.url === "/api/state")).toBe(false);
  serve((url, m) => (m === "POST" ? POST() : url === "/api/state" ? json(200, state([cand("c_1")])) : json(200, J)));
  await show(state([cand("c_1")]), "c_1");
  await click(btn("반영 안 함"));
  expect(el.querySelector("#save-error")!.textContent).toBe("저장 여부를 확인하지 못했어요. 새로 고침해 확인해 주세요.");
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
  await click(btn("고쳐서 남기기"));
  const ta = el.querySelector("textarea")!;
  await act(async () => { Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!.call(ta, "수정한 판단"); ta.dispatchEvent(new Event("input", { bubbles: true })); });
  await click(btn("고친 문장으로 남기기")); await redraw();

  expect(el.textContent).toContain("이 질문의 미결 문장 검토가 끝났어요.");
  expect(el.textContent).not.toContain("방금 확정한 판단");
  expect(el.querySelector('a[href="#structure/cand/confirmed"]')?.textContent).toBe("전체 확정 판단 보기");
});

test("마지막 문장을 반영 안 함으로 처리해도 확정 완료로 오인시키지 않는다", async () => {
  POST = () => json(200, {});
  reload.mockImplementation(async () => { S = state([cand("c_1", { status: "excluded" })]); return true; });
  await show(state([cand("c_1")]), "c_1");
  await click(btn("반영 안 함")); await redraw();

  expect(el.textContent).toContain("이 질문의 미결 문장 검토가 끝났어요.");
  expect(el.textContent).not.toContain("확정했어요");
  expect(el.querySelector('a[href="#structure/cand/confirmed"]')?.textContent).toBe("전체 확정 판단 보기");
});

test("건너뛰기로 목록 끝에 도달하면 남은 문장 분기를 유지하고 완료 안내를 보이지 않는다", async () => {
  await show(state([cand("c_1")]), "c_1");
  await click(btn("건너뛰기")); await follow();

  expect(el.textContent).toContain("목록 끝이에요. 아직 안 정한 문장 1개가 남아 있어요.");
  expect(el.querySelector('a[href="#q/review/q1/c_1"]')?.textContent).toBe("남은 문장 보기");
  expect(el.querySelector('a[href="#structure/cand/confirmed"]')).toBeNull();
  expect(el.textContent).not.toContain("미결 문장 검토가 끝났어요");
});

test("저장 오류는 완료 화면이나 전체 확정 판단 링크로 바뀌지 않는다", async () => {
  POST = () => json(400, { code: "CANDIDATE-REVIEW", msg: "근거가 바뀌었어요." });
  await show(state([cand("c_1")]), "c_1");
  await click(btn("반영 안 함"));

  expect(el.querySelector("#save-error")?.textContent).toBe("근거가 바뀌었어요.");
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
  await click(btn("고쳐서 남기기"));
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
  await click(btn("고쳐서 남기기"));
  await typeIn(el.querySelector("textarea")!, "떠나기 전");
  expect(setDirty).toHaveBeenLastCalledWith("#q/review/q1/c_1");
  act(() => root.unmount());
  expect(setDirty).toHaveBeenLastCalledWith(null);
  root = createRoot(el);
});

test("미저장 보호 — 저장 실패면 그대로 · 저장 성공이면 다시 받기 전에 해제(다시 받기 실패로 카드가 남아도)", async () => {
  await show(state([cand("c_1")]), "c_1");
  await click(btn("고쳐서 남기기"));
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
      <div id={"box-" + id}><Card S={state([])} c={cand(id) as never} head={null} qText="도입 순서는?" byRec={false} w={WORDS} prev="" next="" locked={false}
        status="" err="" onDecide={() => {}} onDirty={d => mark(id, d)} /></div>);
    return <>{one("c_1")}{one("c_2")}</>;
  }
  await act(async () => root.render(<QueryClientProvider client={queryClient}><Two /></QueryClientProvider>));
  await flush(); await flush();
  const box = (id: string) => el.querySelector("#box-" + id)!;
  const inBox = (id: string, t: string) => [...box(id).querySelectorAll("button")].find(b => b.textContent === t) as HTMLButtonElement;
  history.replaceState(null, "", "#q/review/q1/c_1");
  await click(inBox("c_1", "고쳐서 남기기")); await typeIn(box("c_1").querySelector("textarea")!, "하나");
  expect(setDirty).toHaveBeenLastCalledWith("#q/review/q1/c_1");
  history.replaceState(null, "", "#q/review/q1/c_2");
  await click(inBox("c_2", "고쳐서 남기기")); await typeIn(box("c_2").querySelector("textarea")!, "둘");
  await click(inBox("c_1", "취소"));
  expect(setDirty).toHaveBeenLastCalledWith("#q/review/q1/c_2");   // c_1 을 풀어도 c_2 는 남는다
  expect(setDirty).not.toHaveBeenLastCalledWith(null);
  await click(inBox("c_2", "취소"));
  expect(setDirty).toHaveBeenLastCalledWith(null);
});

test("미저장 보호 — 편집 칸을 연 채 남기기·반영 안 함은 고친 문장을 저장한 게 아니다: 다시 받기에 실패해도 등록은 취소·떠날 때까지 남는다", async () => {
  await show(state([cand("c_1")]), "c_1");
  await click(btn("고쳐서 남기기"));
  await typeIn(el.querySelector("textarea")!, "고친 문장");
  expect(setDirty).toHaveBeenLastCalledWith("#q/review/q1/c_1");
  expect(btn("남기기").disabled).toBe(false);   // 편집 칸이 열려 있어도 결정 버튼은 켜져 있다
  reload.mockResolvedValue(false);   // 결정은 저장됐지만 상태를 다시 받지 못함 — 카드·편집 칸이 그대로 남는다
  await click(btn("남기기"));
  expect(posts().at(-1)!.body).toMatchObject({ action: "confirm" });
  expect(el.querySelector("[data-candidate-id]")).not.toBeNull();
  expect(el.querySelector("textarea")!.value).toBe("고친 문장");
  expect(setDirty).toHaveBeenLastCalledWith("#q/review/q1/c_1");
  expect(setDirty).not.toHaveBeenCalledWith(null);
  await click(btn("취소"));   // 기준은 원래 문장 그대로 — 취소하면 원래 문장으로 돌아가고 해제
  expect(setDirty).toHaveBeenLastCalledWith(null);
  await click(btn("고쳐서 남기기"));
  expect(el.querySelector("textarea")!.value).toBe("담당을 먼저 정한다 c_1");
  await typeIn(el.querySelector("textarea")!, "또 고친 문장");
  setDirty.mockClear();
  await click(btn("반영 안 함"));
  expect(posts().at(-1)!.body).toMatchObject({ action: "exclude" });
  expect(setDirty).not.toHaveBeenCalledWith(null);
  expect(el.querySelector("textarea")!.value).toBe("또 고친 문장");
  act(() => root.unmount());   // 화면을 떠나면 해제
  expect(setDirty).toHaveBeenLastCalledWith(null);
  root = createRoot(el);
});

test("고친 문장 저장 응답 유실 — 다시 읽은 상태가 바뀌었고 같은 문장이어도 이 요청의 저장 증거가 아니다: 저장 알림·해제·다시 받기·이동 없이 고치던 문장과 불확실 문구를 남긴다", async () => {
  await show(state([cand("c_1")]), "c_1");
  await click(btn("고쳐서 남기기"));
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
  expect(el.querySelector("#save-status")!.textContent).not.toContain("남겼어요");
  expect(el.querySelector("#save-error")!.textContent).toBe("저장 여부를 확인하지 못했어요. 새로 고침해 확인해 주세요.");
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
  await click(btn("고쳐서 남기기"));
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

  await click(btn("고쳐서 남기기"));
  await typeIn(el.querySelector("textarea")!, "최신 문장에서 시작한 초안");
  await click(btn("고친 문장으로 남기기"));
  expect(posts().at(-1)!.body).toEqual({ candidate_id: "c_1", action: "edit_confirm", expected_revision: 3, text: "최신 문장에서 시작한 초안" });
});

test("원격 변경 뒤 초안을 기준 문장으로 되돌리면 최신 원격 문장과 revision으로 동기화한다", async () => {
  await show(state([cand("c_1", { revision: 2 })]), "c_1");
  await click(btn("고쳐서 남기기"));
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
  ["exclude", "confirmed", "반영 안 함"],
  ["exclude", "excluded", "반영 안 함"],
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
  expect(el.querySelector("#save-error")!.textContent).toBe("저장 여부를 확인하지 못했어요. 새로 고침해 확인해 주세요.");
  expect(el.querySelector("#save-status")!.textContent).not.toContain("남겼어요");
});
