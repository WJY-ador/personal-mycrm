// 문의 데스크(옛 test_web_home.py A1·A2 문의 정적 절을 옮김) — 대화창 한쪽만(보내기 | 내 문의) · 종류 넷(개인정보 요청 = 골라서 연다) · 바이트 상한 ·
// POST /api/feedback {kind, text, page} · 실패 = 서버 문구 · 내 문의 목록·빈 상태·못 읽음 · 상세(보낸 글·답변·공개 이력)는 글자로만 · 설정 「문의 및 개인정보」
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { SCREENS } from "../../test/screens";
import { queryClient } from "../../shared/queries";
import type { AppState } from "../../shared/state";
import { calls, click, flush, installFetch, json, serve, text } from "../../test/fakeServer";
import { deskPage } from "./model";
import { histText } from "./DeskTicket";
import { DESK, DESK_NOTICE } from "./text";
import sample from "./desk.sample.json";

const reload = vi.fn(async () => {});
const S = { user: { display_name: "홍길동", nav: "new" }, tabs: [{ id: "t-001", label: "일지", blocks: ["journal"] }, { id: "t-002", label: "질문", blocks: ["sheet"] }] };
let el: HTMLDivElement, root: Root;
let list: () => Response, one: () => Response, post: () => Response;
async function show(name: string, args: string[] = [], state: object = S) {
  const Screen = SCREENS[name];
  await act(async () => root.render(<QueryClientProvider client={queryClient}><Screen ctx={{ reload, state: state as AppState, args }} /></QueryClientProvider>));
  await flush(); await flush();
}
async function type(v: string) {
  const t = el.querySelector("textarea")!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!.call(t, v);
    t.dispatchEvent(new Event("input", { bubbles: true }));
  });
}
const dlg = () => el.querySelector("#desk-dlg") as HTMLDialogElement;
const sendBtn = () => [...el.querySelectorAll("button")].find(b => b.textContent === "보내기")!;
const posts = () => calls.filter(c => c.method === "POST");

beforeEach(() => {
  installFetch(); queryClient.clear(); history.replaceState(null, "", "#_me");
  list = () => json(200, sample.list);
  one = () => json(200, sample.one);
  post = () => json(200, { id: "tk_new", notice: DESK_NOTICE });
  serve((url, m) => (m === "POST" ? post() : url === "/api/feedback" ? list() : one()));
  HTMLDialogElement.prototype.showModal = function (this: HTMLDialogElement) { this.open = true; };
  HTMLDialogElement.prototype.close = function (this: HTMLDialogElement) { this.open = false; this.dispatchEvent(new Event("close")); };
  el = document.createElement("div"); document.body.append(el); root = createRoot(el);
});
afterEach(() => { act(() => root.unmount()); el.remove(); vi.unstubAllGlobals(); });

test("닫힌 채 자리만 → 「문의 보내기」 = 폼만 · 종류 넷(버그 기본) · 고지·처리방침 · 0 바이트 = [보내기] 꺼짐 · 글 칸 포커스", async () => {
  await show("desk");
  expect(dlg().open).toBe(false);
  expect(calls.length).toBe(0);
  await show("desk", ["send"]);
  expect(dlg().open).toBe(true);
  expect(el.querySelector("#desk-dlg-title")!.textContent).toBe("문의 보내기");
  expect((el.querySelector("#desk-form") as HTMLElement).hidden).toBe(false);
  expect((el.querySelector("#desk-mine") as HTMLElement).hidden).toBe(true);
  expect(text(el, "fieldset label")).toEqual([" 버그", " 요청", " 질문", " 개인정보 요청"]);
  expect((el.querySelector('input[value="bug"]') as HTMLInputElement).checked).toBe(true);
  expect(el.querySelector("#desk-notice")!.textContent).toContain(DESK_NOTICE);
  expect(el.querySelector('#desk-notice a[href="/privacy"]')).not.toBeNull();
  expect(el.querySelector("#desk-count")!.textContent).toBe("0 / 4096 바이트");
  expect(sendBtn().disabled).toBe(true);
  expect(document.activeElement).toBe(el.querySelector("#desk-text"));
  expect(calls.length).toBe(0);
});

test("바이트 = UTF-8 · 넘치면 「너무 길어요」 + 꺼짐 · 보내기 = POST 1(kind·text·page) · 글 비움 + 안내 · 실패 = 서버 문구(없으면 화면 문구)", async () => {
  history.replaceState(null, "", "#t-001");
  await show("desk", ["send"]);
  await type("가".repeat(1366));
  expect(el.querySelector("#desk-count")!.textContent).toBe("4098 / 4096 바이트 — 너무 길어요");
  expect(sendBtn().disabled).toBe(true);
  await type("저장이 안 돼요");
  expect(el.querySelector("#desk-count")!.textContent).toBe("20 / 4096 바이트");
  await click(el.querySelector('input[value="question"]'));
  post = () => json(400, { code: "RATE-LIMIT", msg: "오늘은 더 보낼 수 없어요." });
  await click(sendBtn());
  expect(el.querySelector('[role="alert"]')!.textContent).toBe("오늘은 더 보낼 수 없어요.");
  post = () => { throw new TypeError("offline"); };
  await click(sendBtn());
  expect(el.querySelector('[role="alert"]')!.textContent).toBe(DESK.sendFail);
  post = () => json(200, { id: "tk_new" });
  await click(sendBtn());
  expect(posts().at(-1)).toEqual({ url: "/api/feedback", method: "POST", body: { kind: "question", text: "저장이 안 돼요", page: "record" } });
  expect((el.querySelector("#desk-text") as HTMLTextAreaElement).value).toBe("");
  expect(el.querySelector('#desk-form [role="status"]')!.textContent).toBe(DESK.sent);
  expect(el.querySelector('[role="alert"]')!.textContent).toBe("");
});

test("「개인정보 요청」 = 종류를 골라 연다 · 「내 문의」 = 목록만(열 때마다 새로) · 행 = 접수일·종류·상태 칩·답변·최근 갱신·글", async () => {
  await show("desk", ["privacy"]);
  expect((el.querySelector('input[value="privacy"]') as HTMLInputElement).checked).toBe(true);
  await show("desk", ["mine"]);
  expect(el.querySelector("#desk-dlg-title")!.textContent).toBe("내 문의");
  expect((el.querySelector("#desk-form") as HTMLElement).hidden).toBe(true);
  expect((el.querySelector("#desk-mine") as HTMLElement).hidden).toBe(false);
  const row = text(el, "tbody td");
  expect(row.slice(1)).toEqual(["버그", "처리중", "있음", row[4], "견본 문의"]);
  expect(el.querySelector("tbody .chip")!.className).toBe("chip flag");
  expect(calls.filter(c => c.url === "/api/feedback").length).toBe(1);
  await show("desk", ["mine"]);
  expect(calls.filter(c => c.url === "/api/feedback").length).toBe(2);
  list = () => json(200, { tickets: [] });
  await show("desk", ["mine"]);
  expect(el.querySelector(".empty")!.textContent).toBe(DESK.empty);
  list = () => json(500, {});
  await show("desk", ["mine"]);
  expect(el.textContent).toContain(DESK.listFail);
});

test("상세 = 겹친 대화창(보낸 글·답변·공개 이력 글자로) · 닫으면 사라짐 · 못 읽음 = 서버 문구", async () => {
  list = () => json(200, { tickets: [{ ...sample.list.tickets[0], text: "<b>굵게</b>" }] });
  one = () => json(200, { ...sample.one, text: "<b>굵게</b>" });
  await show("desk", ["mine"]);
  await click(el.querySelector("tbody button"));
  const tk = el.querySelector("[aria-labelledby=desk-tk-title]") as HTMLDialogElement;
  expect(tk.open).toBe(true);
  expect(calls.at(-1)!.url).toBe("/api/feedback/tk_sample1");
  expect(el.querySelector("#desk-tk-title")!.textContent).toBe("내 문의 · 버그");
  expect(tk.textContent).toContain("<b>굵게</b>");
  expect(tk.querySelector("b:not(#desk-tk-title)")).toBeNull();
  expect(tk.textContent).toContain("견본 답변");
  expect(text(tk, "li")[0]).toMatch(/ · 상태 접수 → 처리중$/);
  await click([...tk.querySelectorAll("button")].find(b => b.textContent === "닫기"));
  expect(el.querySelector("[aria-labelledby=desk-tk-title]")).toBeNull();
  one = () => json(404, { code: "NOT-FOUND", msg: "문의를 찾을 수 없어요." });
  await click(el.querySelector("tbody button"));
  expect(el.querySelector("[aria-labelledby=desk-tk-title]")!.textContent).toContain("문의를 찾을 수 없어요.");
});

test("상세 다시 받기 실패(합성) — 받아 둔 글은 그대로 + role=alert 안내 · 첫 받기 실패 = 안내만(글·alert 없음)", async () => {
  let detailGets = 0;
  serve((url, m) => {
    if (m === "POST") return post();
    if (url === "/api/feedback") return list();
    if (m === "GET" && url === "/api/feedback/tk_sample1") {
      detailGets += 1;
      return detailGets === 1 ? json(200, sample.one) : json(500, { code: "SERVER", msg: "잠시 뒤 다시 해 주세요." });
    }
    return json(404, {});
  });
  await show("desk", ["mine"]);
  await click(el.querySelector("tbody button"));
  const tk = () => el.querySelector("[aria-labelledby=desk-tk-title]") as HTMLDialogElement;
  expect(detailGets).toBe(1);
  expect(tk().textContent).toContain("견본 문의");
  expect(tk().querySelector('[role="alert"]')).toBeNull();
  expect(queryClient.getQueryData(["desk", "one", "tk_sample1"])).toEqual(sample.one);
  await act(async () => { await queryClient.invalidateQueries({ queryKey: ["desk", "one", "tk_sample1"], exact: true }); });
  await flush(); await flush();
  expect(detailGets).toBe(2);
  expect(calls.filter(c => c.method === "GET" && c.url === "/api/feedback/tk_sample1").length).toBe(2);
  expect(el.querySelector("#desk-tk-title")!.textContent).toBe("내 문의 · 버그");
  expect(tk().querySelector("p")!.textContent).toBe("잠시 뒤 다시 해 주세요.");
  expect(tk().querySelector('[role="alert"]')!.textContent).toBe("잠시 뒤 다시 해 주세요.");
  expect(text(tk(), "h3")).toEqual(["보낸 글", "운영자 답변", "처리 이력"]);
  expect(tk().textContent).toContain("견본 문의");
  expect(tk().textContent).toContain("견본 답변");
  expect(text(tk(), "li")[0]).toMatch(/ · 상태 접수 → 처리중$/);
  await click([...tk().querySelectorAll("button")].find(b => b.textContent === "닫기"));
  expect(tk()).toBeNull();
  serve((url, m) => (m === "GET" && url === "/api/feedback" ? list() : json(500, {})));
  await click(el.querySelector("tbody button"));
  expect(calls.at(-1)!.url).toBe("/api/feedback/tk_sample1");
  expect(tk().querySelector(".db")!.textContent).toBe(DESK.oneFail);
  expect(tk().querySelector('[role="alert"]')).toBeNull();
  expect(tk().querySelector("h3")).toBeNull();
  expect(el.querySelector("#desk-tk-title")!.textContent).toBe("내 문의");
});

test("공개 이력 한 줄 — 상태 바뀜 · 답변 바뀜 · 삭제 완료", () => {
  expect([{ kind: "status", from_val: "open", to_val: "done" }, { kind: "reply", from_val: null, to_val: null }, { kind: "deleted", from_val: null, to_val: null }]
    .map(h => histText({ ...h, at: "" }))).toEqual(["상태 접수 → 완료", "운영자 답변이 바뀌었어요", "삭제 완료"]);
});

test("보낸 자리(page) — 판단 대조 · 사용자 탭(기록형·질문형) · 옛 화면 · 그 밖 = other(서버 TICKET_PAGES 안)", () => {
  const st = S as unknown as AppState;
  expect(["#q/review/q1/c1", "#t-001", "#t-002", "#journal", "#q", "#structure/x", "#_me", "#_today", "#_setup/help", "", "#t-009"].map(h => deskPage(st, h)))
    .toEqual(["review", "record", "question", "record", "question", "structure", "other", "other", "other", "other", "other"]);
  expect(deskPage({ ...st, read: { tabs: { ok: false } } } as AppState, "#t-001")).toBe("other");
  expect(deskPage(undefined, "#q")).toBe("other");
});

test("설정 「문의 및 개인정보」 — 버튼 셋(껍데기 data-open 이 대화창을 연다) · 관리자 = 안내 한 줄 · 처리방침", async () => {
  await show("help");
  expect([...el.querySelectorAll("[data-open]")].map(b => [b.getAttribute("data-open"), b.textContent])).toEqual([["send", "문의 보내기"], ["mine", "내 문의"], ["privacy", "개인정보 요청"]]);
  expect(el.querySelector('a[href="/privacy"]')).not.toBeNull();
  await show("help", [], { ...S, user: { ...S.user, admin: true } });
  expect(el.querySelectorAll("[data-open]").length).toBe(0);
  expect(el.textContent).toContain(DESK.noDesk);
});
