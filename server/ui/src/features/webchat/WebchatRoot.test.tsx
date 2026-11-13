// 웹 「대화」 화면 — 스위치 꺼짐 = 버튼·패널 0 · 켜짐 = 탭 줄 AI 버튼 · 열면 입력 칸 하나 + 모델 고르기 · 첫 메시지로 시작 · 턴(도구 접힘·답·중지)
// · 모델 없음 한 줄 · PC 허용 대기(기다림 캐릭터) · 지난 대화 목록 · 확인 카드(사람 말, 값이 빠지지 않음, 원본은 자세히 안) · 남의 데이터 없음.
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import type { AppState } from "../../shared/state";
import { flush } from "../../test/fakeServer";
import { ApiFail } from "../../shared/api";
import type { Approval } from "./api";
import { WebchatStore } from "./store";
import { WebchatRoot } from "./WebchatRoot";
import { AI_UNLINKED, EMPTY, END, GRANT, GUIDE_OFFLINE, GUIDE_RECHECK, GUIDE_STEPS, GUIDE_TITLE, HISTORY_NOTE, MORE_MODELS, NO_MODEL, OP_NAME, PC_ON, PICK_SWITCH, TITLE, WAITING } from "./text";

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
  expect(a.textContent).toBe(TITLE); expect(TITLE).toBe("AI");   // AI 하나로 A1
  expect(aside().hidden).toBe(true);
  await act(async () => { a.click(); }); await flush(); await flush();
  expect(aside().hidden).toBe(false);
  expect(aside().querySelectorAll("textarea").length).toBe(1);
  expect(aside().querySelector('input[type="radio"]')).toBeNull();   // 옛 라디오 묶음 없음
  const pick = aside().querySelector("[aria-haspopup=dialog]") as HTMLButtonElement;
  expect(pick.textContent).toContain("시험용 가짜 AI, 기본 모델");
  expect(aside().textContent).toContain("대화 기록은 서버에 30일 보관돼요.");
  expect(aside().textContent).toContain("AI는 내 판단 대시보드의 도구만 써요.");
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

// 보안 검토 1: 무장 지연과 해제를 실제 시간 없이 본다(store.now, store.later 주입)
const clock = (s: WebchatStore) => {
  let t = 0;
  const q: { at: number; fn: () => void; live: boolean }[] = [];
  s.now = () => t;
  s.later = (fn, ms) => { const x = { at: t + ms, fn, live: true }; q.push(x); return () => { x.live = false; }; };
  return { tick(ms: number) { t += ms; for (const x of q.filter(x => x.live && x.at <= t)) { x.live = false; x.fn(); } } };
};

const leaves = (v: unknown): string[] => v === null ? [] : Array.isArray(v) ? v.flatMap(leaves) : typeof v === "object" ? Object.entries(v as object).flatMap(([k, x]) => [k, ...leaves(x)]) : [String(v)];

test("확인 카드 = op 한국어 제목 · shown 의 이름과 값이 빠짐없이 보인다(자세히 밖) · 원문은 인용 · 원본 JSON 은 자세히 안 · 되돌릴 수 없으면 두 번 확인(A5)", async () => {
  const { s } = mk();
  const c = clock(s);
  const shown = { "기록": "회고", "전": "<script>alert(1)</script> 옛 글", "후": "새 글", "지워질 판단 후보": ["후보 하나", "후보 둘"], "제안": { "title": "새 제목", "body": null }, "근거 인용": "원문 그대로" };
  const card: Approval = { id: "ap_1", turn_id: "ct_1", op: "record_edit", params: { record_id: "r1", find: "옛", replace: "새" }, shown, impact: { record_id: "r1", revision: 3 }, irreversible: true, status: "pending", created_at: "", expires_at: "2026-11-08T00:05:00Z", finished_at: null, result: null };
  s.api.approvals = vi.fn().mockResolvedValue({ approvals: [card] });
  await open(s);
  await type("고쳐 줘"); await send(); await flush();
  const art = el.querySelector("article") as HTMLElement;
  expect(art.querySelector("h5")?.textContent).toBe(OP_NAME.record_edit);
  expect(art.querySelector("[data-irreversible-note]")?.textContent).toBe("되돌릴 수 없어요");
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
  const buttons = () => [...art.querySelectorAll("[data-card-buttons] > button")].map(b => b.textContent);
  expect(buttons()).toEqual(["취소", "확인하고 실행"]);
  s.api.approvals = vi.fn().mockResolvedValue({ approvals: [{ ...card, status: "confirmed", finished_at: "2026-11-08T00:01:00Z", result: { updated: 1, record: { title: "changed" } } }] });
  await act(async () => { btn("확인하고 실행").click(); }); await flush();
  expect(s.api.confirmApproval).not.toHaveBeenCalled();   // 첫 확인은 서버로 가지 않는다
  expect(art.querySelector("[role=alert]")?.textContent).toBe("되돌릴 수 없는 작업이에요. 실행하려면 한 번 더 눌러 주세요.");
  // 보안 검토 1: 정말 실행은 확인하고 실행 자리에 생기지 않는다(경고 줄 왼쪽), 1초 동안 비활성
  expect(buttons()).toEqual(["그만두기"]);
  const armRow = art.querySelector("[data-arm-row]") as HTMLElement;
  expect([...armRow.children].map(x => x.textContent)).toEqual(["정말 실행", "되돌릴 수 없는 작업이에요. 실행하려면 한 번 더 눌러 주세요."]);
  expect(btn("정말 실행").disabled).toBe(true);
  await act(async () => { btn("정말 실행").click(); btn("정말 실행").dispatchEvent(new MouseEvent("dblclick", { bubbles: true })); }); await flush();
  expect(s.api.confirmApproval).not.toHaveBeenCalled();   // 무장 직후 클릭, 더블클릭 = 실행 안 함
  await act(async () => { btn("그만두기").click(); }); await flush();
  expect(buttons()).toEqual(["취소", "확인하고 실행"]);
  // 카드 밖을 누르면 바로 풀린다
  await act(async () => { btn("확인하고 실행").click(); }); await flush();
  expect(art.querySelector("[data-arm-row]")).toBeTruthy();
  await act(async () => { document.body.dispatchEvent(new Event("pointerdown", { bubbles: true })); }); await flush();
  expect(art.querySelector("[data-arm-row]")).toBeNull();
  expect(buttons()).toEqual(["취소", "확인하고 실행"]);
  // 1초 뒤 클릭 = 실행
  await act(async () => { btn("확인하고 실행").click(); }); await flush();
  await act(async () => { c.tick(1000); }); await flush();
  expect(btn("정말 실행").disabled).toBe(false);
  await act(async () => { btn("정말 실행").click(); }); await flush(); await flush();
  expect(s.api.confirmApproval).toHaveBeenCalledTimes(1);
  expect(s.api.confirmApproval).toHaveBeenCalledWith("cs_1", "ap_1", true);
  expect(el.textContent).toContain('"updated": 1');
});

test("A6 대화 기록 카드 = 기록 남기기 제목 · 전문이 자르지 않고 보이고 가공 방식, 내 결정 표시가 보인다 · 되돌릴 수 있으면 한 번 확인", async () => {
  const { s } = mk();
  const body = "### 확인 카드를 두 번 누르게\n영구 삭제가 한 번에 나가면 안 된다고 내가 정했다. 그래서 정말 실행을 한 번 더 두었다.\n동기: 대화에 없음";
  const shown = { "본문": body, "제목": "AI 대화 정리", "가공 방식": "AI가 정리한 글", "내 결정 표시": "판단 근거로 쓰는 내 정리(결정은 내가 했어요)" };
  const card: Approval = { id: "ca_9", turn_id: "ct_1", op: "record_add", params: { text: body, text_process: "structured", decision_owner: "self" }, shown, impact: { tier: "write" }, irreversible: false, status: "pending", created_at: "", expires_at: "2026-11-08T00:05:00Z", finished_at: null, result: null };
  s.api.approvals = vi.fn().mockResolvedValue({ approvals: [card] });
  await open(s);
  await type("이 대화 남겨 줘"); await send(); await flush();
  const art = el.querySelector("article") as HTMLElement;
  expect(art.querySelector("h5")?.textContent).toBe("기록 남기기");
  expect(art.querySelector("[data-irreversible-note]")).toBeNull();
  const box = art.querySelector("[data-shown]") as HTMLElement;
  expect(box.querySelector("blockquote")?.textContent).toBe(body);
  for (const v of ["가공 방식", "AI가 정리한 글", "내 결정 표시", "판단 근거로 쓰는 내 정리(결정은 내가 했어요)"]) expect(box.textContent).toContain(v);
  await act(async () => { btn("확인하고 실행").click(); }); await flush(); await flush();
  expect(s.api.confirmApproval).toHaveBeenCalledWith("cs_1", "ca_9", false);
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

// ── 대화 하나로 J(2026-11-12) ──
test("J-F1(앱 하나): 쓸 수 있는 AI가 없으면 연결 안내 2단계, 멈춘 단계 = 서버 setup, PC 앱 받기 = none 만, 다시 확인", async () => {
  for (const [setup, states, links] of [
    ["none", ["now", "todo"], ["/download"]],
    ["offline", ["now", "todo"], []],
    ["no_provider", ["done", "now"], []],
    ["no_link", ["done", "now"], []],
  ] as const) {
    const { s } = mk();
    s.api.capabilities = vi.fn(async () => ({ devices: [], setup }));
    await open(s);
    const g = aside().querySelector(`section[data-setup="${setup}"]`) as HTMLElement;
    expect(g).not.toBeNull();
    expect(g.textContent).toContain(GUIDE_TITLE);
    expect([...g.querySelectorAll("li")].map(li => li.getAttribute("data-state"))).toEqual(states);
    expect([...g.querySelectorAll("li")].map(li => li.querySelector("h5")!.firstChild!.textContent!.trim())).toEqual(GUIDE_STEPS.map(x => x.title));
    expect([...g.querySelectorAll("a")].map(a => a.getAttribute("href"))).toEqual(links);
    expect(g.querySelector("[href^=\"mycrm:\"]")).toBeNull();   // 연결 장치 창 딥링크는 없앴다
    if (setup === "offline") expect(g.textContent).toContain(GUIDE_OFFLINE);
    expect(aside().textContent).not.toContain(EMPTY);
    await act(async () => { btn(GUIDE_RECHECK, g).click(); }); await flush();
    expect(s.api.capabilities).toHaveBeenCalledTimes(2);
    act(() => root.unmount()); root = createRoot(el);
  }
  const { s } = mk();   // 고를 AI가 있으면 안내 없음
  await open(s);
  expect(aside().querySelector("section[data-setup]")).toBeNull();
});

test("앱 하나 1.3: 새 앱(ai_links)은 linked 공급자만 고르고, 허용 요청 없이 바로 세션을 연다", async () => {
  const { s } = mk();
  s.api.capabilities = vi.fn(async () => ({ devices: [{ device_id: "is_1", connected: true, agent_version: "1.0", capabilities_version: 2,
    capabilities: [{ provider: "claude" as const, models: ["sonnet"] }, { provider: "codex" as const, models: ["gpt"] }],
    ai_links: { claude: "linked" as const, codex: "signed_out" as const } }] }));
  await open(s);
  expect(s.choices().map(c => c.provider)).toEqual(["claude"]);
  await type("안녕");
  await send();
  expect(s.api.grant).not.toHaveBeenCalled();
  expect(s.api.create).toHaveBeenCalledWith("is_1", "claude", "sonnet", expect.any(String));
});

test("앱 하나 1.3: 새 앱인데 그새 끊김(CONSENT_REQUIRED) = 허용 창 대신 다시 연결 안내, 선택지 다시 읽기", async () => {
  const { s } = mk();
  s.api.capabilities = vi.fn(async () => ({ devices: [{ device_id: "is_1", connected: true, agent_version: "1.0", capabilities_version: 2,
    capabilities: [{ provider: "claude" as const, models: ["sonnet"] }], ai_links: { claude: "linked" as const } }] }));
  s.api.create = vi.fn(async () => { throw new ApiFail({ code: "CONSENT_REQUIRED", msg: "", status: 409 }); });
  await open(s);
  await type("안녕");
  await send();
  expect(s.api.grant).not.toHaveBeenCalled();
  expect(aside().textContent).toContain(AI_UNLINKED);
  expect(s.api.capabilities).toHaveBeenCalledTimes(2);
});

test("앱 하나 1.3: 앱 다리가 있으면 AI 연결 줄 — 끊김은 [Claude 연결] 하나, 연결됨은 [연결 끊기], CLI 없음은 줄 없음", async () => {
  const calls: string[] = [];
  let push: (v: unknown) => void = () => {};
  const state = { providers: [{ provider: "claude", state: "signed_out", code: null }, { provider: "codex", state: "missing", code: null }] };
  (window as unknown as { mycrmDesktop: unknown }).mycrmDesktop = { ai: {
    get: async () => state, onChange: (cb: (v: unknown) => void) => { push = cb; return () => {}; },
    connect: async (p: string) => { calls.push("connect:" + p); }, disconnect: async (p: string) => { calls.push("disconnect:" + p); } } };
  try {
    const { s } = mk();
    await open(s);
    const links = () => aside().querySelector("[aria-label='이 PC의 AI 연결']") as HTMLElement;
    expect([...links().querySelectorAll("p")].map(p => p.getAttribute("data-ai"))).toEqual(["claude"]);
    await act(async () => { btn("Claude 연결", links()).click(); }); await flush();
    expect(calls).toEqual(["connect:claude"]);
    await act(async () => { push({ providers: [{ provider: "claude", state: "linked", code: null }] }); }); await flush();
    expect(s.api.capabilities).toHaveBeenCalledTimes(2);   // 연결이 끝나면 서버 선택지를 다시 읽는다
    await act(async () => { btn("연결 끊기", links()).click(); }); await flush();
    expect(calls).toEqual(["connect:claude", "disconnect:claude"]);
  } finally { delete (window as unknown as { mycrmDesktop?: unknown }).mycrmDesktop; }
});

test("J-F4: 입력 칸 Enter = 보내기, Shift+Enter = 보내지 않음(줄바꿈), 한글 조합 중 Enter = 보내지 않음", async () => {
  const { s } = mk();
  await open(s);
  await type("엔터로 보내기");
  const ta = aside().querySelector("textarea") as HTMLTextAreaElement;
  const key = (init: KeyboardEventInit & { keyCode?: number }) => act(async () => { ta.dispatchEvent(new KeyboardEvent("keydown", { bubbles: true, cancelable: true, ...init })); });
  await key({ key: "Enter", shiftKey: true });
  await key({ key: "Enter", isComposing: true });
  await flush();
  expect(s.api.create).not.toHaveBeenCalled();
  await key({ key: "Enter" });
  await flush(); await flush();
  expect(s.api.create).toHaveBeenCalledTimes(1);
  expect(s.api.turn).toHaveBeenCalledTimes(1);
});

test("J-F5: 모델 목록 = 고른 것(✓ 표시, 굵게)과 포인터(옅은 바탕)가 다른 모양, 계열마다 최신만 위에, 나머지는 다른 모델 아래 접힘, 고른 것이 접힌 쪽이면 펼침", async () => {
  const { s } = mk();
  s.api.capabilities = vi.fn(async () => ({ devices: [{ device_id: "is_1", connected: true, agent_version: "1", capabilities_version: 2,
    capabilities: [{ provider: "claude" as const, models: ["claude-opus-5", "claude-opus-5-5", "claude-haiku-5-5", "claude-haiku-4-5"] }] }] }));
  await open(s);
  await act(async () => { (aside().querySelector("[aria-haspopup=dialog]") as HTMLButtonElement).click(); }); await flush();
  let pop = aside().querySelector("#webchat-models") as HTMLElement;
  const top = [...pop.querySelectorAll(":scope > ul > li > button")].map(b => b.textContent);
  expect(top).toEqual(["Claude, claude-opus-5-5", "Claude, claude-haiku-5-5"]);
  const more = pop.querySelector("details") as HTMLDetailsElement;
  expect(more.querySelector("summary")!.textContent).toBe(`${MORE_MODELS} 2개`);
  expect(more.open).toBe(false);
  expect([...pop.querySelectorAll("button[aria-pressed=true]")].map(b => b.textContent)).toEqual(["Claude, claude-opus-5-5"]);   // 기억 없으면 접히지 않은 첫 모델
  await act(async () => { s.togglePicker(false); });
  s.pick({ device: "is_1", provider: "claude", model: "claude-haiku-4-5" });
  await act(async () => { (aside().querySelector("[aria-haspopup=dialog]") as HTMLButtonElement).click(); }); await flush();
  pop = aside().querySelector("#webchat-models") as HTMLElement;
  expect((pop.querySelector("details") as HTMLDetailsElement).open).toBe(true);
  expect([...pop.querySelectorAll("button[aria-pressed=true]")].map(b => b.textContent)).toEqual(["Claude, claude-haiku-4-5"]);
});

test("R-J3: 창 focus, 탭이 다시 보이면 capabilities 다시 읽기, 연달아 오면 한 번, 숨김 상태와 닫힌 뒤는 읽지 않음", async () => {
  const { s } = mk();
  let t = 0;
  s.now = () => t;
  await open(s);
  const n = () => (s.api.capabilities as ReturnType<typeof vi.fn>).mock.calls.length;
  const base = n();
  t = 5000;
  await act(async () => { window.dispatchEvent(new Event("focus")); document.dispatchEvent(new Event("visibilitychange")); }); await flush();
  expect(n()).toBe(base + 1);
  t = 10000;
  Object.defineProperty(document, "visibilityState", { configurable: true, get: () => "hidden" });
  try {
    await act(async () => { document.dispatchEvent(new Event("visibilitychange")); }); await flush();
    expect(n()).toBe(base + 1);
  } finally { delete (document as { visibilityState?: string }).visibilityState; }
  act(() => root.unmount());
  root = createRoot(el);
  s.open = true; t = 20000;   // 닫힌 패널 조건이 아니라 리스너를 뗐는지 본다
  window.dispatchEvent(new Event("focus")); document.dispatchEvent(new Event("visibilitychange")); await flush();
  expect(n()).toBe(base + 1);
});

test("R-J2: 허용 해제로 끝난 턴(끝 이벤트 code CONSENT_REQUIRED) = 해제 문구가 보이고 내부 code는 보이지 않음", async () => {
  const { s, fire } = mk();
  await open(s);
  await type("안녕");
  await send();
  fire("turn", { turn_id: "ct_1", text: "안녕" });
  fire("error", { turn_id: "ct_1", seq: 1, data: { code: "CONSENT_REQUIRED" } });
  const turn = aside().querySelector("[data-turn=ct_1]") as HTMLElement;
  expect(END.CONSENT_REQUIRED).toBe("이 PC의 대화 허용이 해제돼 답을 멈췄어요.");
  expect(turn.textContent).toContain(END.CONSENT_REQUIRED);
  expect(aside().textContent).not.toContain("CONSENT_REQUIRED");
  expect(btn("중지")).toBeUndefined();
});
