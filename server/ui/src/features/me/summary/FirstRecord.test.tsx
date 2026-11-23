// 첫 기록 카드(2026-11-23 4차) — 입력칸 하나와 [남기기]. 저장 = POST /api/records {text} 하나, 저장 중 잠금, 빈 글 = 버튼 꺼짐,
// Cmd/Ctrl+Enter(한글 조합 중 무시), 저장 뒤 이 화면에 머무는 동안 저장됨 모양, 떠났다 오면 카드 없음, 미저장 보호 등록과 해제, 실패 문구.
// 복사 줄 시험은 설정 AI 앱 연결 쪽으로 옮겼다(features/connect/ConnectScreen.test.tsx)
import { act } from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { queryClient } from "../../../shared/queries";
import { calls, click, flush, installFetch, json, serve } from "../../../test/fakeServer";
import { installMedia, layout, meState, STATS } from "../../../test/meFixture";
import { hideMe, setDirty, showMe, type } from "../../../test/showMe";
import { FIRST_CONNECT, FIRST_HELP, FIRST_LABEL, FIRST_SAVED, FIRST_UNKNOWN } from "./FirstRecord";

const EMPTY = { ...meState(), journal: [], journal_next_before: null };
const ONE = meState();   // 글 1편(다시 받은 뒤)
let inval: ReturnType<typeof vi.spyOn>;
let post: (body: unknown) => Response | Promise<Response> = () => json(200, { id: "r_new", title: "첫 글", created: "2026-11-23T03:00:00Z" });
beforeEach(() => {
  installFetch(); installMedia(false); queryClient.clear();
  setDirty.mockClear();
  inval = vi.spyOn(queryClient, "invalidateQueries");   // 저장 뒤 다시 받기 = 껍데기 reload 와 같은 모든 조회 무효화
  post = () => json(200, { id: "r_new", title: "첫 글", created: "2026-11-23T03:00:00Z" });
  serve((url, method) => {
    if (url === "/api/records" && method === "POST") return post(calls.at(-1)!.body);
    if (url === "/api/me/layout") return json(200, layout());
    if (url === "/api/me/stats") return json(200, STATS);
    return json(404, { code: "NOT-FOUND", msg: "" });
  });
});
afterEach(() => { hideMe(); vi.unstubAllGlobals(); inval.mockRestore(); });
const posts = () => calls.filter(c => c.method !== "GET");
const card = (el: Element) => el.querySelector("#first-record-intro");
const area = (el: Element) => el.querySelector("#first-record-intro textarea") as HTMLTextAreaElement;
const save = (el: Element) => el.querySelector("#first-record-intro button[type=submit]") as HTMLButtonElement;
const key = async (el: Element, o: KeyboardEventInit) => { await act(async () => { el.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true, ...o })); }); await flush(); };

test("모양 — 입력칸 하나(라벨), 한 줄 설명, [남기기] 하나(빈 글이면 꺼짐), 입력칸에 포커스, 주소와 복사 버튼 없음, 요청 0", async () => {
  const el = await showMe("#_me/summary", EMPTY);
  const c = card(el)!;
  expect(c.querySelector("label")!.textContent).toBe(FIRST_LABEL);
  expect(c.querySelector("label")!.getAttribute("for")).toBe("first-record-input");
  expect(c.querySelector(".hint")!.textContent).toBe(FIRST_HELP);
  expect([...c.querySelectorAll("button")].map(b => b.textContent)).toEqual(["남기기"]);
  expect(save(el).disabled).toBe(true);
  expect(document.activeElement).toBe(area(el));
  expect(c.textContent).not.toContain("/mcp");
  expect(c.querySelector("code")).toBeNull();
  await type(area(el), "   ");
  expect(save(el).disabled).toBe(true);   // 공백만 = 빈 글
  expect(posts()).toEqual([]);
});

test("저장 — 본문 그대로 {text} 하나, 저장 중 잠금, 다시 받기, 이 화면에 머무는 동안 저장됨 모양과 연결 링크, 떠났다 오면 카드 없음", async () => {
  let done!: (r: Response) => void;
  post = () => new Promise<Response>(r => { done = r; });
  const el = await showMe("#_me/summary", EMPTY);
  await type(area(el), "  오늘 회의에서\n담당을 먼저 정했다  ");
  expect(save(el).disabled).toBe(false);
  await click(save(el));
  expect(posts()).toEqual([{ url: "/api/records", method: "POST", body: { text: "  오늘 회의에서\n담당을 먼저 정했다  " } }]);
  expect(area(el).disabled).toBe(true);
  expect(save(el).disabled).toBe(true);
  await click(save(el));   // 잠긴 동안 다시 눌러도 요청 0
  expect(posts().length).toBe(1);
  await act(async () => { done(json(200, { id: "r_new", title: "첫 글", created: "2026-11-23T03:00:00Z" })); });
  await flush(); await flush();
  expect(inval).toHaveBeenCalledTimes(1);
  const c = card(el)!;
  expect(c.querySelector("textarea")).toBeNull();
  expect(c.querySelector("[role=status]")!.textContent).toBe(`${FIRST_SAVED} ${FIRST_CONNECT}`);
  const a = c.querySelector("a")!;
  expect(a.getAttribute("href")).toBe("#_setup/connect");
  expect(document.activeElement).toBe(a);
  expect(c.querySelector("[role=alert]")!.textContent).toBe("");
  // 다시 받은 상태(글 1편) — 카드 조건은 거짓이지만 이 화면에 머무는 동안 저장됨 모양은 남는다
  await showMe("#_me/summary", ONE);
  expect(card(el)!.querySelector("[role=status]")!.textContent).toBe(`${FIRST_SAVED} ${FIRST_CONNECT}`);
  hideMe();
  const again = await showMe("#_me/summary", ONE);
  expect(card(again)).toBeNull();
  expect(posts().length).toBe(1);
});

test("미저장 보호 — 적으면 이 주소로 등록, 비우면 해제, 저장하면 해제", async () => {
  const el = await showMe("#_me/summary", EMPTY);
  await type(area(el), "적는 중");
  expect(setDirty).toHaveBeenLastCalledWith("#_me/summary");
  await type(area(el), "");
  expect(setDirty).toHaveBeenLastCalledWith(null);
  await type(area(el), "다시 적음");
  expect(setDirty).toHaveBeenLastCalledWith("#_me/summary");
  await click(save(el));
  await flush();
  expect(posts().length).toBe(1);
  expect(setDirty).toHaveBeenLastCalledWith(null);
});

test("Cmd/Ctrl+Enter = 저장, 한글 조합 중과 Enter 만은 무시, 빈 글은 요청 0, 연타는 한 번", async () => {
  const el = await showMe("#_me/summary", EMPTY);
  await key(area(el), { metaKey: true });
  expect(posts()).toEqual([]);   // 빈 글
  await type(area(el), "한 줄");
  await key(area(el), { metaKey: true, isComposing: true });
  await key(area(el), {});
  expect(posts()).toEqual([]);
  let done!: (r: Response) => void;
  post = () => new Promise<Response>(r => { done = r; });
  await act(async () => {
    area(el).dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", ctrlKey: true, bubbles: true }));
    area(el).dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", ctrlKey: true, bubbles: true }));
  });
  expect(posts()).toEqual([{ url: "/api/records", method: "POST", body: { text: "한 줄" } }]);
  await act(async () => { done(json(200, { id: "r_new", title: "한 줄", created: "2026-11-23T03:00:00Z" })); });
  await flush();
  expect(card(el)!.querySelector("[role=status]")!.textContent).toContain(FIRST_SAVED);
});

test("서버 거절 = 서버 문구 그 자리, 글은 그대로, 다시 누를 수 있다", async () => {
  post = () => json(400, { code: "PAYLOAD-LIMIT", msg: "글이 너무 길어요." });
  const el = await showMe("#_me/summary", EMPTY);
  await type(area(el), "긴 글");
  await click(save(el));
  expect(card(el)!.querySelector("[role=alert]")!.textContent).toBe("글이 너무 길어요.");
  expect(area(el).value).toBe("긴 글");
  expect(area(el).disabled).toBe(false);
  expect(save(el).disabled).toBe(false);
  expect(inval).not.toHaveBeenCalled();
  expect(setDirty).toHaveBeenLastCalledWith("#_me/summary");
});

test("응답을 못 받음(연결 끊김) = 저장 여부를 모른다는 한 줄, 글은 그대로", async () => {
  post = () => Promise.reject(new TypeError("offline"));
  const el = await showMe("#_me/summary", EMPTY);
  await type(area(el), "끊긴 글");
  await click(save(el));
  expect(card(el)!.querySelector("[role=alert]")!.textContent).toBe(FIRST_UNKNOWN);
  expect(area(el).value).toBe("끊긴 글");
  expect(save(el).disabled).toBe(false);
  expect(card(el)!.querySelector("[role=status]")!.textContent).toBe("");
});

// 나 머리의 표시 이름 편집(공용 편집 장치, 칸 id hedit-input)과 부딪치지 않는다 — 이름 칸이 열려 있어도 저장 1건, id 겹침 0, 저장 중 이름을 눌러도 잠금 유지
const nameBtn = (el: Element) => el.querySelector(".hhead button[title='눌러서 고치기']") as HTMLButtonElement;
test("이름 편집 칸이 열린 채 [남기기] = 저장 요청 1건과 저장됨, 입력칸 id 는 이름 칸과 겹치지 않는다", async () => {
  const el = await showMe("#_me/summary", EMPTY);
  await type(area(el), "이름 칸이 열린 채 적은 글");
  await click(nameBtn(el));
  expect(el.querySelectorAll("#hedit-input").length).toBe(1);   // 이름 칸 하나뿐
  expect(el.querySelector(".hhead #hedit-input")).toBeTruthy();
  expect(area(el).id).toBe("first-record-input");
  expect(el.querySelectorAll("#first-record-input").length).toBe(1);
  expect(el.querySelector("label[for='first-record-input']")!.textContent).toBe(FIRST_LABEL);
  await click(save(el));
  expect(posts()).toEqual([{ url: "/api/records", method: "POST", body: { text: "이름 칸이 열린 채 적은 글" } }]);
  expect(card(el)!.querySelector("[role=status]")!.textContent).toBe(`${FIRST_SAVED} ${FIRST_CONNECT}`);
  expect(el.querySelector(".hhead #hedit-input")).toBeTruthy();   // 이름 칸은 그대로 열려 있다
});

test("저장 중에 이름을 눌러도 입력칸과 버튼은 잠긴 채, 다시 눌러도 요청 1건", async () => {
  let done!: (r: Response) => void;
  post = () => new Promise<Response>(r => { done = r; });
  const el = await showMe("#_me/summary", EMPTY);
  await type(area(el), "저장 중");
  await click(save(el));
  expect(posts().length).toBe(1);
  await click(nameBtn(el));
  expect(el.querySelector(".hhead #hedit-input")).toBeTruthy();
  expect(area(el).disabled).toBe(true);
  expect(save(el).disabled).toBe(true);
  await key(area(el), { metaKey: true });
  expect(posts().length).toBe(1);
  await act(async () => { done(json(200, { id: "r_new", title: "저장 중", created: "2026-11-23T03:00:00Z" })); });
  await flush(); await flush();
  expect(card(el)!.querySelector("[role=status]")!.textContent).toBe(`${FIRST_SAVED} ${FIRST_CONNECT}`);
  expect(posts().length).toBe(1);
});
