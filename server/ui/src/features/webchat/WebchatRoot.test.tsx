// 웹 「대화」 화면 — 스위치 꺼짐 = 버튼·패널 0 · 켜짐 = 탭 줄 「AI 대화」 버튼 · 열면 입력 칸 하나 + 모델 고르기 · 첫 메시지로 시작 · 턴(도구 접힘·답·중지)
// · 모델 없음 한 줄 · PC 허용 대기(기다림 캐릭터) · 지난 대화 목록 · 확인 카드(사람 말, 값이 빠지지 않음, 원본은 자세히 안) · 남의 데이터 없음.
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import type { AppState } from "../../shared/state";
import { flush } from "../../test/fakeServer";
import type { Approval } from "./api";
import { WebchatStore } from "./store";
import { WebchatRoot } from "./WebchatRoot";
import { GRANT, HISTORY_NOTE, NO_MODEL, OP_NAME, PC_ON, PICK_SWITCH, TITLE, WAITING } from "./text";

let el: HTMLDivElement, nav: HTMLSpanElement, root: Root;
beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  nav = document.createElement("span"); nav.id = "ui-chatnav";
  el = document.createElement("div");
  document.body.append(nav, el); root = createRoot(el);
});
afterEach(() => { act(() => root.unmount()); el.remove(); nav.remove(); });
const st = (webchat: boolean, dev = "recent") => ({ user: { display_name: "홍길동", nav: "new" }, switches: { trash: false, webchat }, devices_status: { state: dev, last_seen_at: null, threshold_seconds: 600 } }) as unknown as AppState;
const reload = vi.fn(async () => {});

function mk() {
  const s = new WebchatStore();
  s.saved = { get: () => null, set: () => {}, drop: () => {} };
  s.sleep = async () => {};
  const ls: Record<string, (e: MessageEvent) => void> = {};
  s.api = {
    sessions: vi.fn(async () => ({ sessions: [] })),
    capabilities: vi.fn(async () => ({ devices: [{ device_id: "is_1", connected: true, agent_version: "1.0", capabilities_version: 2, capabilities: [{ provider: "fake" as const, models: [null] }, { provider: "claude" as const, models: ["sonnet"] }] }] })),
    create: vi.fn(async (device_id: string, provider: string, model: string | null) => ({ session_id: "cs_1", status: "active", device_id, connected: true, provider, model, binding_version: 2 })),
    resume: vi.fn(async () => ({ session_id: "cs_1", status: "active", device_id: "is_1", connected: true, provider: "fake", model: null, binding_version: 2 })),
    grant: vi.fn(async (device_id: string, provider: string, model: string | null, request_id: string) => ({ request_id, device_id, provider, model, state: "pending" as const, prompt: "none" as const, expires_at: "" })),
    grantStatus: vi.fn(async (request_id: string) => ({ request_id, device_id: "is_1", provider: "claude", model: "sonnet", state: "approved" as const, prompt: "done" as const, expires_at: "", connected: true })),
    messages: vi.fn(async () => ({ messages: [] })),
    turn: vi.fn(async () => ({ turn_id: "ct_1", status: "running", created: true })),
    stop: vi.fn(async () => ({ turn_id: "ct_1" })),
    approvals: vi.fn(async () => ({ approvals: [] })),
    confirmApproval: vi.fn(async () => ({ status: "confirmed" as const, result: { updated: 1, record: { title: "changed" } } })),
    cancelApproval: vi.fn(async () => ({ status: "cancelled" as const })),
    stream: vi.fn(() => ({ onmessage: null, onerror: null, close() {}, addEventListener: (t: string, f: (e: MessageEvent) => void) => { ls[t] = f; } })),
  };
  const fire = (t: string, d: unknown) => act(() => ls[t]({ data: JSON.stringify(d) } as MessageEvent));
  return { s, fire };
}
const aside = () => el.querySelector("aside#webchat") as HTMLElement;
const btn = (label: string, scope: ParentNode = el) => [...scope.querySelectorAll("button")].find(b => b.textContent === label) as HTMLButtonElement;
async function open(s: WebchatStore, dev = "recent") {
  await act(async () => root.render(<WebchatRoot ctx={{ reload, state: st(true, dev) }} store={s} />));
  await act(async () => { (nav.querySelector("a") as HTMLAnchorElement).click(); }); await flush(); await flush();
}
async function type(text: string) {
  const ta = aside().querySelector("textarea") as HTMLTextAreaElement;
  const set = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!;
  await act(async () => { set.call(ta, text); ta.dispatchEvent(new Event("input", { bubbles: true })); });
}
async function send() { await act(async () => { btn("보내기").click(); }); await flush(); await flush(); }

test("스위치 꺼짐 = 버튼·패널 0", async () => {
  const { s } = mk();
  await act(async () => root.render(<WebchatRoot ctx={{ reload, state: st(false) }} store={s} />));
  expect(nav.childElementCount).toBe(0);
  expect(el.querySelector("aside#webchat")).toBeNull();
});

test("켜짐 = 입력 칸 하나 + 모델 고르기 · 시작 단계 없이 첫 메시지로 대화 · 턴(도구 접힘·답 굵게·중지) · 남의 데이터 없음", async () => {
  const { s, fire } = mk();
  await act(async () => root.render(<WebchatRoot ctx={{ reload, state: st(true) }} store={s} />));
  const a = nav.querySelector("a") as HTMLAnchorElement;
  expect(a.textContent).toBe(TITLE);
  expect(aside().hidden).toBe(true);
  await act(async () => { a.click(); }); await flush(); await flush();
  expect(aside().hidden).toBe(false);
  expect(aside().querySelectorAll("textarea").length).toBe(1);
  expect(aside().querySelector('input[type="radio"]')).toBeNull();   // 옛 라디오 묶음 없음
  const pick = aside().querySelector("[aria-haspopup=dialog]") as HTMLButtonElement;
  expect(pick.textContent).toContain("시험용 가짜 AI, 기본 모델");
  expect(aside().textContent).toContain("대화 기록은 서버에 30일 보관돼요.");
  expect(aside().textContent).toContain("도구는 내 판단 대시보드(my-crm)만 써요.");
  expect(s.api.create).not.toHaveBeenCalled();
  await type("안녕");
  await send();
  expect(s.api.create).toHaveBeenCalledWith("is_1", "fake", null, expect.any(String));
  expect(s.api.turn).toHaveBeenCalledWith("cs_1", "안녕", expect.any(String));
  expect(aside().querySelector("[aria-label='대화 정보'] [role=status]")?.textContent).toBe(`시험용 가짜 AI, 기본 모델, ${PC_ON}`);
  fire("turn", { turn_id: "ct_1", text: "안녕", user_id: "u-other", email: "other@example.com" });
  const turn = () => aside().querySelector("[data-turn=ct_1]") as HTMLElement;
  expect(turn().querySelector("[role=status]")?.textContent).toBe(WAITING);   // 기다림 캐릭터 = 낭독기 글자 하나
  expect(turn().querySelector("svg[data-sprout]")?.getAttribute("aria-hidden")).toBe("true");
  fire("tool_call", { turn_id: "ct_1", seq: 1, data: { name: "find", input: { q: "x" } } });
  fire("delta", { turn_id: "ct_1", seq: 2, data: { text: "**중요** 답" } });
  expect(turn().querySelector("p")?.textContent).toBe("안녕");
  expect(turn().querySelector("details summary")?.textContent).toBe("도구 1번 사용");
  expect(turn().querySelector("strong")?.textContent).toBe("중요");
  expect(turn().querySelector("svg[data-sprout]")).toBeNull();
  expect(aside().textContent).not.toContain("other@example.com");
  const stop = btn("중지");
  expect(stop).toBeTruthy();
  expect(btn("보내기").disabled).toBe(true);   // 실행 중 = 보내기 잠금
  await act(async () => { stop.click(); });
  expect(s.api.stop).toHaveBeenCalledWith("cs_1");
  fire("done", { turn_id: "ct_1", seq: 3, data: {} });
  expect(btn("중지")).toBeUndefined();
});

test("모델 목록 열림 = 서버가 준 것만 · 진행 중 대화에서 다른 모델 = 확인 문구 뒤 새 대화", async () => {
  const { s, fire } = mk();
  await open(s);
  await type("안녕"); await send();
  fire("turn", { turn_id: "ct_1", text: "안녕" }); fire("done", { turn_id: "ct_1", seq: 1, data: {} });
  await act(async () => { (aside().querySelector("[aria-haspopup=dialog]") as HTMLButtonElement).click(); }); await flush();
  const pop = aside().querySelector("#webchat-models") as HTMLElement;
  expect([...pop.querySelectorAll("button")].map(b => [b.textContent, b.getAttribute("aria-pressed")])).toEqual([["시험용 가짜 AI, 기본 모델", "true"], ["Claude, sonnet", "false"]]);
  await act(async () => { btn("Claude, sonnet", pop).click(); });
  expect(aside().textContent).toContain(PICK_SWITCH);
  await act(async () => { btn("새 대화 시작").click(); });
  expect([s.sid, s.choice?.provider]).toEqual(["", "claude"]);
  expect(aside().querySelector("[data-turn]")).toBeNull();
});

test("모델 없음 = 빈 목록 대신 이유 한 줄(연결 장치 상태로 구분)", async () => {
  for (const dev of ["none", "offline", "recent"]) {
    const { s } = mk();
    s.api.capabilities = vi.fn(async () => ({ devices: [] }));
    await open(s, dev);
    await act(async () => { (aside().querySelector("[aria-haspopup=dialog]") as HTMLButtonElement).click(); }); await flush();
    expect(aside().querySelector("#webchat-models")?.textContent).toBe(NO_MODEL[dev]);
    expect(btn("보내기").disabled).toBe(true);
    act(() => root.unmount()); root = createRoot(el);
  }
});

test("PC 허용 대기 = 기다림 캐릭터 + 허용을 눌러 달라는 글 · 입력 잠김 · 허용되면 보낸다", async () => {
  const { s } = mk();
  let release!: () => void;
  s.sleep = () => new Promise<void>(r => { release = r; });
  await open(s);
  await act(async () => { s.pick(s.choices()[1]); });
  await type("질문");
  await act(async () => { btn("보내기").click(); }); await flush();
  const box = aside().querySelector("[aria-label='PC 허용']") as HTMLElement;
  expect(box.querySelector("[role=status]")?.textContent).toBe(GRANT.none);
  expect(box.querySelector("svg[data-sprout]")).toBeTruthy();
  expect((aside().querySelector("textarea") as HTMLTextAreaElement).disabled).toBe(true);
  await act(async () => { release(); }); await flush(); await flush();
  expect(s.api.create).toHaveBeenCalledWith("is_1", "claude", "sonnet", (s.api.grant as ReturnType<typeof vi.fn>).mock.calls[0][3]);
  expect(s.api.turn).toHaveBeenCalledWith("cs_1", "질문", expect.any(String));
  expect(aside().querySelector("[aria-label='PC 허용']")).toBeNull();
});

test("지난 대화 목록 = 보관 안내 한 줄 + 세션 목록 · 열면 읽기 전용", async () => {
  const { s } = mk();
  await open(s);
  s.api.sessions = vi.fn(async () => ({ sessions: [{ session_id: "cs_0", status: "closed", device_id: "is_1", provider: "claude", model: "opus", binding_version: 2, created_at: "2026-11-09T01:00:00Z" }] }));
  s.api.messages = vi.fn(async () => ({ messages: [{ id: "m1", turn_id: "ct_a", role: "user" as const, body: "예전 질문", created_at: "", turn_status: "done" }, { id: "m2", turn_id: "ct_a", role: "assistant" as const, body: "예전 답", created_at: "", turn_status: "done" }] }));
  await act(async () => { btn("지난 대화").click(); }); await flush();
  const list = aside().querySelector("[aria-label='지난 대화']") as HTMLElement;
  expect(list.textContent).toContain(HISTORY_NOTE);
  expect(list.querySelector("button")?.textContent).toContain("Claude, opus");
  await act(async () => { list.querySelector("button")!.click(); }); await flush();
  expect(aside().textContent).toContain("예전 답");
  expect(aside().querySelector("textarea")).toBeNull();
  await act(async () => { btn("새 대화", aside().querySelector("[data-past-foot]")!).click(); });
  expect(aside().querySelector("textarea")).toBeTruthy();
});

const leaves = (v: unknown): string[] => v === null ? [] : Array.isArray(v) ? v.flatMap(leaves) : typeof v === "object" ? Object.entries(v as object).flatMap(([k, x]) => [k, ...leaves(x)]) : [String(v)];

test("확인 카드 = op 한국어 제목 · shown 의 이름과 값이 빠짐없이 보인다(자세히 밖) · 원문은 인용 · 원본 JSON 은 자세히 안 · 버튼 그대로", async () => {
  const { s } = mk();
  const shown = { "기록": "회고", "전": "<script>alert(1)</script> 옛 글", "후": "새 글", "지워질 판단 후보": ["후보 하나", "후보 둘"], "제안": { "title": "새 제목", "body": null }, "근거 인용": "원문 그대로" };
  const card: Approval = { id: "ap_1", turn_id: "ct_1", op: "record_edit", params: { record_id: "r1", find: "옛", replace: "새" }, shown, impact: { record_id: "r1", revision: 3 }, irreversible: true, status: "pending", created_at: "", expires_at: "2026-11-08T00:05:00Z", finished_at: null, result: null };
  s.api.approvals = vi.fn().mockResolvedValue({ approvals: [card] });
  await open(s);
  await type("고쳐 줘"); await send(); await flush();
  const art = el.querySelector("article") as HTMLElement;
  expect(art.querySelector("h5")?.textContent).toBe(OP_NAME.record_edit);
  expect(art.textContent).toContain("되돌릴 수 없음");
  const visible = art.querySelector("[data-shown]") as HTMLElement;
  for (const leaf of leaves(shown)) expect(visible.textContent).toContain(leaf);
  expect(visible.textContent).toContain("없음");   // null 도 줄로 남는다
  expect([...visible.querySelectorAll("blockquote")].map(b => b.textContent)).toEqual(["<script>alert(1)</script> 옛 글", "새 글", "원문 그대로"]);
  expect(art.querySelector("script")).toBeNull();
  expect(visible.textContent).not.toContain("{");   // JSON 그대로가 아니다
  const raw = art.querySelector("details") as HTMLDetailsElement;
  expect(raw.open).toBe(false);
  expect(raw.querySelector("summary")?.textContent).toBe("자세히");
  expect(raw.textContent).toContain('"replace": "새"');
  expect(raw.textContent).toContain('"revision": 3');
  expect([...art.querySelectorAll(":scope > div > button")].map(b => b.textContent)).toEqual(["취소", "확인하고 실행"]);
  s.api.approvals = vi.fn().mockResolvedValue({ approvals: [{ ...card, status: "confirmed", finished_at: "2026-11-08T00:01:00Z", result: { updated: 1, record: { title: "changed" } } }] });
  await act(async () => { btn("확인하고 실행").click(); }); await flush(); await flush();
  expect(s.api.confirmApproval).toHaveBeenCalledWith("cs_1", "ap_1");
  expect(el.textContent).toContain('"updated": 1');
});

test("PC 앱이 허용하지 않음(declined) = 새 대화 안내 문구, 대기 캐릭터 없음", async () => {
  const { s } = mk();
  s.sleep = async () => {};
  s.api.grantStatus = vi.fn(async (request_id: string) => ({ request_id, device_id: "is_1", provider: "claude", model: "sonnet", state: "pending" as const, prompt: "declined" as const, expires_at: "", connected: true }));
  await open(s);
  await act(async () => { s.pick(s.choices()[1]); });
  await type("질문");
  await act(async () => { btn("보내기").click(); }); await flush(); await flush();
  const box = aside().querySelector("[aria-label='PC 허용']") as HTMLElement;
  expect(box.querySelector("[role=alert]")?.textContent).toBe(GRANT.declined);
  expect(GRANT.declined).toBe("PC 앱에서 허용하지 않았어요. 다시 시작하려면 새 대화를 여세요.");
  expect(box.querySelector("svg[data-sprout]")).toBeNull();
  expect(s.api.create).not.toHaveBeenCalled();
});

test("write 카드 = 한국어 제목 · 긴 본문을 자르지 않고 높이 제한 스크롤 상자 안에 전부 보인다", async () => {
  const { s } = mk();
  const long = "가".repeat(5000) + "끝";
  const shown = { "본문": long, "제목": "회의 메모", "질문 ID": "", "출처 메모": "대화에서 입력", "모르는_키": "그대로" };
  const card: Approval = { id: "ca_1", turn_id: "ct_1", op: "record_add", params: { text: long }, shown, impact: { tier: "write" }, irreversible: false, status: "pending", created_at: "", expires_at: "2026-11-08T00:05:00Z", finished_at: null, result: null };
  s.api.approvals = vi.fn().mockResolvedValue({ approvals: [card] });
  await open(s);
  await type("남겨 줘"); await send(); await flush();
  const art = el.querySelector("article") as HTMLElement;
  expect(art.querySelector("h5")?.textContent).toBe(OP_NAME.record_add);
  const box = art.querySelector("[data-shown]") as HTMLElement;
  expect(box.getAttribute("role")).toBe("region");
  expect(box.tabIndex).toBe(0);
  expect(box.querySelector("blockquote")?.textContent).toBe(long);   // 자르지 않는다
  for (const k of Object.keys(shown)) expect(box.textContent).toContain(k);
  expect(box.textContent).toContain("빈 값");
});

test("확인 카드: 모르는 op = op 이름 그대로 · 승인 목록 오류를 표시하고 다시 불러올 수 있다 · 빈 목록이면 상자가 없다", async () => {
  const { s } = mk();
  s.api.approvals = vi.fn().mockRejectedValueOnce(new Error("offline")).mockResolvedValue({ approvals: [{ id: "ap_x", turn_id: "ct_1", op: "new_op", params: {}, shown: "한 줄", impact: {}, irreversible: false, status: "pending", created_at: "", expires_at: "", finished_at: null, result: null }] });
  await open(s);
  await type("x"); await send();
  expect(el.textContent).toContain("확인 요청을 불러오지 못했어요");
  await act(async () => { btn("목록 새로고침").click(); }); await flush();
  expect(el.querySelector("article h5")?.textContent).toBe("new_op");
  expect(el.querySelector("article [data-shown]")?.textContent).toBe("한 줄");
  s.api.approvals = vi.fn(async () => ({ approvals: [] }));
  await act(async () => { btn("목록 새로고침").click(); }); await flush();
  expect(el.querySelector("[aria-label='확인할 작업']")).toBeNull();
});
