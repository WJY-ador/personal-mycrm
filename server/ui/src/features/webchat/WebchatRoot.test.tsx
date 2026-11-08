// 웹 「대화」 화면 — 스위치 꺼짐 = 버튼·패널 0 · 켜짐 = 탭 줄 「AI 대화」 버튼 · 열면 패널(PC 상태·턴·도구 접힘·답·중지) · 남의 데이터 없음.
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import type { AppState } from "../../shared/state";
import { flush } from "../../test/fakeServer";
import { WebchatStore } from "./store";
import { WebchatRoot } from "./WebchatRoot";
import { PC_ON, TITLE } from "./text";

let el: HTMLDivElement, nav: HTMLSpanElement, root: Root;
beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  nav = document.createElement("span"); nav.id = "ui-chatnav";
  el = document.createElement("div");
  document.body.append(nav, el); root = createRoot(el);
});
afterEach(() => { act(() => root.unmount()); el.remove(); nav.remove(); });
const st = (webchat: boolean) => ({ user: { display_name: "홍길동", nav: "new" }, switches: { trash: false, webchat } }) as unknown as AppState;
const reload = vi.fn(async () => {});

function mk() {
  const s = new WebchatStore();
  const ls: Record<string, (e: MessageEvent) => void> = {};
  s.api = {
    sessions: vi.fn(async () => ({ sessions: [] })),
    capabilities: vi.fn(async () => ({ devices: [{ device_id: "is_1", connected: true, agent_version: "1.0", capabilities_version: 2, capabilities: [{ provider: "claude" as const, models: ["sonnet"] }] }] })),
    create: vi.fn(async () => ({ session_id: "cs_1", status: "active", device_id: "is_1", connected: true, provider: "claude", model: "sonnet", binding_version: 2 })),
    resume: vi.fn(async () => ({ session_id: "cs_1", status: "active", device_id: "is_1", connected: true, provider: "claude", model: "sonnet", binding_version: 2 })),
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

async function chooseSession() {
  const radio = el.querySelector('input[type="radio"]') as HTMLInputElement;
  await act(async () => { radio.click(); });
  const launch = [...el.querySelectorAll("button")].find(b => b.textContent === "이 선택으로 시작")!;
  await act(async () => { launch.click(); }); await flush(); await flush();
}

test("스위치 꺼짐 = 버튼·패널 0", async () => {
  const { s } = mk();
  await act(async () => root.render(<WebchatRoot ctx={{ reload, state: st(false) }} store={s} />));
  expect(nav.childElementCount).toBe(0);
  expect(el.querySelector("aside#webchat")).toBeNull();
});

test("켜짐 = 버튼 → 패널 · PC 연결 · 턴(사용자 글·도구 접힘·답 굵게·중지) · 남의 데이터 없음", async () => {
  const { s, fire } = mk();
  await act(async () => root.render(<WebchatRoot ctx={{ reload, state: st(true) }} store={s} />));
  const a = nav.querySelector("a") as HTMLAnchorElement;
  expect(a.textContent).toBe(TITLE);
  const aside = () => el.querySelector("aside#webchat") as HTMLElement;
  expect(aside().hidden).toBe(true);
  await act(async () => { a.click(); }); await flush();
  expect(aside().hidden).toBe(false);
  expect(aside().querySelector("header [role=status]")?.textContent).toBe("");
  expect(s.api.create).not.toHaveBeenCalled();
  expect(aside().querySelector("fieldset legend")?.textContent).toBe("is_1, 연결됨");
  expect(aside().querySelector("fieldset label")?.textContent).toBe("claude, sonnet");
  const choice = aside().querySelector('input[type="radio"]') as HTMLInputElement;
  await act(async () => { choice.click(); });
  const launch = [...aside().querySelectorAll("button")].find(b => b.textContent === "이 선택으로 시작") as HTMLButtonElement;
  await act(async () => { launch.click(); }); await flush();
  expect(aside().querySelector("header [role=status]")?.textContent).toBe(`claude, sonnet, ${PC_ON}`);
  fire("turn", { turn_id: "ct_1", text: "안녕", user_id: "u-other", email: "other@example.com" });
  fire("tool_call", { turn_id: "ct_1", seq: 1, data: { name: "find", input: { q: "x" } } });
  fire("delta", { turn_id: "ct_1", seq: 2, data: { text: "**중요** 답" } });
  const turn = aside().querySelector("[data-turn=ct_1]") as HTMLElement;
  expect(turn.querySelector("p")?.textContent).toBe("안녕");
  expect(turn.querySelector("details summary")?.textContent).toBe("도구 1번 사용");
  expect(turn.querySelector("strong")?.textContent).toBe("중요");
  expect(aside().textContent).not.toContain("other@example.com");
  const stop = [...aside().querySelectorAll("button")].find(b => b.textContent === "중지") as HTMLButtonElement;
  expect(stop).toBeTruthy();
  const send = [...aside().querySelectorAll("button")].find(b => b.textContent === "보내기") as HTMLButtonElement;
  expect(send.disabled).toBe(true);   // 실행 중 = 보내기 잠금
  await act(async () => { stop.click(); });
  expect(s.api.stop).toHaveBeenCalledWith("cs_1");
  fire("done", { turn_id: "ct_1", seq: 3, data: {} });
  expect([...aside().querySelectorAll("button")].some(b => b.textContent === "중지")).toBe(false);
});

test("승인 카드에 shown, impact, params 전체를 안전한 텍스트로 표시하고 확인·취소를 제공한다", async () => {
  const { s } = mk();
  const payload = { approvals: [{ id: "ap_1", turn_id: "ct_1", op: "update", params: { nested: { message: "<script>alert(1)</script>", fields: ["a", "b"] } }, shown: { title: "화면 표시", rows: [{ text: "전체 표시" }] }, impact: { affected: 2 }, irreversible: true, status: "pending" as const, created_at: "2026-11-08T00:00:00Z", expires_at: "2026-11-08T00:05:00Z", finished_at: null, result: null }] };
  s.api.approvals = vi.fn().mockResolvedValueOnce(payload).mockResolvedValue({ approvals: [{ ...payload.approvals[0], status: "confirmed", finished_at: "2026-11-08T00:01:00Z", result: { updated: 1, record: { title: "changed" } } }] });
  await act(async () => root.render(<WebchatRoot ctx={{ reload, state: st(true) }} store={s} />));
  const a = nav.querySelector("a") as HTMLAnchorElement;
  await act(async () => { a.click(); }); await flush(); await flush();
  await chooseSession();
  const card = el.querySelector("article") as HTMLElement;
  expect(card.textContent).toContain("되돌릴 수 없음");
  expect(card.textContent).toContain('"message": "<script>alert(1)</script>"');
  expect(card.textContent).toContain('"fields": [\n      "a",\n      "b"');
  expect(card.querySelector("script")).toBeNull();
  expect([...card.querySelectorAll("button")].map(b => b.textContent)).toEqual(["취소", "확인하고 실행"]);
  const confirm = [...card.querySelectorAll("button")].find(b => b.textContent === "확인하고 실행")!;
  await act(async () => { confirm.click(); }); await flush(); await flush();
  expect(s.api.confirmApproval).toHaveBeenCalledWith("cs_1", "ap_1");
  expect(s.api.approvals).toHaveBeenCalled();
  expect(el.textContent).toContain('"updated": 1');
  expect(el.textContent).toContain('"title": "changed"');
});

test("승인 목록 오류를 표시하고 다시 불러올 수 있다", async () => {
  const { s } = mk();
  s.api.approvals = vi.fn().mockRejectedValueOnce(new Error("offline")).mockResolvedValue({ approvals: [] });
  await act(async () => root.render(<WebchatRoot ctx={{ reload, state: st(true) }} store={s} />));
  const a = nav.querySelector("a") as HTMLAnchorElement;
  await act(async () => { a.click(); }); await flush(); await flush();
  await chooseSession();
  expect(el.textContent).toContain("확인 요청을 불러오지 못했어요");
  const refresh = [...el.querySelectorAll("button")].find(b => b.textContent === "목록 새로고침")!;
  await act(async () => { refresh.click(); }); await flush();
  expect(el.textContent).toContain("대기 중인 확인 요청이 없어요.");
});
