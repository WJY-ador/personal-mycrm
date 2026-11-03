// 판단 검토(원문과 대조하기) — 옛 app.html renderReview·decide 동작을 옮긴 시험(R3). 껍데기 라우터 대신 주소(history)와 ctx(상태·args)를 직접 넘긴다.
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { SCREENS } from "../../layout/registry";
import { queryClient } from "../../shared/queries";
import type { AppState } from "../../shared/state";
import { calls, click, flush, installFetch, json, serve } from "../../test/fakeServer";

const BODY = "# 도입 회고\n\n첫 문단이다.\n\n고객은 입력 담당을 먼저 정했다. 그게 맞았다.\n\n셋째 문단.\n\n넷째 문단은 멀다.";
const J = { id: "r1", title: "도입 회고", body: BODY, revision: 1, author_kind: "self", meta: { created: "2026-11-02T01:00:00Z", source: "파일:a.md", question_id: "q1" } };
const cand = (id: string, x: object = {}) => ({ id, text: "담당을 먼저 정한다 " + id, status: "pending", record_id: "r1", question_id: "q1", quote: "입력 담당을 먼저",
  review: null, revision: 2, created: "2026-11-02T01:00:00Z", origin: "ai", edited_by_user: false, wording_by: "ai", wording_approved: false, ...x });
const state = (cands: object[], nav = "new", x: object = {}) => ({
  user: { display_name: "홍길동", nav }, switches: { trash: true }, questions: [{ id: "q1", text: "도입 순서는?", created: "" }],
  journal: [{ id: "r1", title: "도입 회고", excerpt: "", created: "", source: null, source_id: "s1", question_id: "q1", source_date: null, author_kind: "self" }],
  sources: [{ id: "s1", kind: "file", name: "회고 메모", location: null }], candidates: cands, ...x }) as unknown as AppState;

let el: HTMLDivElement, root: Root, S: AppState, args: string[];
const reload = vi.fn(async () => true);
async function show(st: AppState, key: string, qid = "q1") {
  S = st; args = ["q", qid, key, "#q/q1", "질문으로 돌아가기"];
  history.replaceState(null, "", `#q/review/${qid}/${key}`);
  const R = SCREENS.review;
  await act(async () => root.render(<QueryClientProvider client={queryClient}><R ctx={{ reload, state: S, args }} /></QueryClientProvider>));
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
  installFetch(); queryClient.clear(); reload.mockReset(); reload.mockResolvedValue(true);
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
  expect(el.querySelector("[data-candidate-id]")!.textContent).toContain("질문 · 도입 순서는?");
  expect([...el.querySelectorAll(".labels > *")].map(x => x.textContent)).toEqual(["아직 안 정함", "AI가 쓴 문장", "AI 문안"]);
  expect(el.querySelector(".recheck")).toBeNull();
  expect(["남기기", "고쳐서 남기기", "반영 안 함"].map(t => btn(t).disabled)).toEqual([true, true, true]);
  expect(el.textContent).toContain("원문을 불러오는 중이에요…");
  serve(() => json(200, J)); queryClient.clear();
  await show(state([cand("c_1"), cand("c_2")]), "c_1");
  expect(["남기기", "고쳐서 남기기", "반영 안 함"].map(t => btn(t).disabled)).toEqual([false, false, false]);
  const src = el.querySelector("#rvsrc")!;
  expect(src.querySelector("h3")!.textContent).toBe("근거 원문 · 도입 회고");
  const ex = src.querySelector(":scope > .doc")!;
  expect([...ex.querySelectorAll("p")].map(p => [p.className, p.textContent])).toEqual([
    ["dim", "첫 문단이다."], ["", "고객은 입력 담당을 먼저 정했다. 그게 맞았다."], ["dim", "셋째 문단."]]);
  expect(ex.querySelector("mark")!.textContent).toBe("입력 담당을 먼저");
  expect(src.querySelector("details.fold summary")!.textContent).toBe("전체 원문 보기");
  expect(src.querySelector("details.tech")!.textContent).toContain("출처 회고 메모 · 파일 · 쓸 당시 표기 「파일에서 가져옴」 · 근거 구절 9자");
  expect(btn("이전 문장").disabled).toBe(true);
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
  expect(el.textContent).toContain("아직 안 정한 문장이 없어요.새 글에서 판단을 뽑으면 여기에 떠요.");
  await show(state([cand("c_9", { question_id: null })]), "c_9", "r:r1");
  expect(el.querySelector("[data-candidate-id]")!.textContent).toContain("질문 없음 · 내 글 「도입 회고」");
  expect(el.querySelector("#decision-help")!.textContent).toBe("남기면 확정한 판단에 들어가요(질문 없음). 반영 안 함으로 둬도 판단 문장과 원문은 삭제되지 않아요. 원문은 바뀌지 않아요.");
  await show(state([], "new", { read: { candidates: { ok: false, error: { code: "OFFLINE", msg: "x" } } } }), "c_1");
  expect(el.querySelector(".partfail")!.textContent).toContain("문장 목록을 읽지 못했어요 · 나머지는 정상서버에 연결하지 못했어요.");
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

test("고쳐서 남기기 · 충돌 = 서버 문구 + 고치던 문장 · 실패 = 서버 msg 그대로(잠금 풀림) · 응답 유실 = 상태 다시 읽어 판정", async () => {
  await show(state([cand("c_1")]), "c_1");
  await click(btn("고쳐서 남기기"));
  const ta = el.querySelector("textarea")!;
  expect(document.activeElement).toBe(ta);
  await act(async () => { Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!.call(ta, "고친 문장"); ta.dispatchEvent(new Event("input", { bubbles: true })); });
  POST = () => json(409, { code: "CONFLICT", msg: "다른 곳에서 먼저 바뀌었어요(서버)." });
  reload.mockImplementation(async () => { S = state([cand("c_1", { revision: 3 })]); return true; });
  await click(btn("고친 문장으로 남기기")); await redraw();
  expect(posts().at(-1)!.body).toEqual({ candidate_id: "c_1", action: "edit_confirm", expected_revision: 2, text: "고친 문장" });
  expect(el.querySelector("#save-status")!.textContent).toBe("다른 곳에서 먼저 바뀌었어요(서버). 고치던 문장은 저장되지 않았어요: 「고친 문장」");
  POST = () => json(400, { code: "CANDIDATE-REVIEW", msg: "근거가 바뀌었어요." });
  await click(btn("반영 안 함"));
  expect(el.querySelector("#save-error")!.textContent).toBe("근거가 바뀌었어요.");
  expect(btn("반영 안 함").disabled).toBe(false);
  // 응답 유실 — 상태의 그 판단이 바뀌었으면 저장된 것
  POST = () => Promise.reject(new TypeError("network"));
  serve((url, m) => (m === "POST" ? POST() : url === "/api/state" ? json(200, state([cand("c_1", { status: "excluded" })])) : json(200, J)));
  reload.mockImplementation(async () => { S = state([]); return true; });
  await click(btn("반영 안 함")); await redraw();
  expect(el.textContent).toContain("아직 안 정한 문장이 없어요.");
  expect(el.querySelector("#save-status")!.textContent).toBe("반영 안 함으로 표시했어요.");
  serve((url, m) => (m === "POST" ? POST() : url === "/api/state" ? json(200, state([cand("c_1")])) : json(200, J)));
  await show(state([cand("c_1")]), "c_1");
  await click(btn("반영 안 함"));
  expect(el.querySelector("#save-error")!.textContent).toBe("저장 여부를 확인하지 못했어요. 새로 고침해 확인해 주세요.");
});

test("옛 탐색 — 옛 말(내 판단·후보·기록)", async () => {
  await show(state([cand("c_1", { review: "processed" })], "old"), "c_1");
  expect(btn("내 판단으로 남기기")).toBeTruthy();
  expect(el.querySelector("#rvacts")!.getAttribute("aria-label")).toBe("후보 결정");
  expect(el.querySelector("#decision-help")!.textContent).toContain("남기면 「도입 순서는?」의 내 판단에 들어가요. 반영 안 함으로 둬도 후보와 원문은 삭제되지 않아요.");
  expect(el.querySelector(".recheck")!.textContent).toContain("가공 방식 정보가 실제로 틀렸을 때만 연결한 AI 대화에서 기록 정보를 정정하세요.");
  expect(el.querySelector("details.tech")!.textContent).toContain("기록 당시 표기");
});
