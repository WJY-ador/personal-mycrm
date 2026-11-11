// 웹 「대화」 상태 — 가짜 서버 접점·가짜 EventSource 로 흐름 단위: 열기 = 세션 + SSE · 재생/실시간 겹침 1번 · 도구 접힘 · 끝 상태 · 보내기 멱등 키 · 오류 문구
// · 모델 고르기(지난번 선택 기억, 사라진 선택 버리기, 진행 중 교체 확인) · PC 허용 흐름(요청, 대기, 허용, 창 닫힘, 시간 초과, PC 꺼짐) · 지난 대화(읽기 전용).
import { expect, test, vi } from "vitest";
import { ApiFail } from "../../shared/api";
import type { Capabilities, Es, Grant } from "./api";
import { MODEL_KEY, WebchatStore, choiceKey, pastTurns, type Saved } from "./store";
import { EMPTY, END, ERR, REPLACED, TEXT_MAX, TRIMMED, errText } from "./text";

class FakeEs implements Es {
  onmessage = null; onerror = null; closed = false;
  ls: Record<string, ((e: MessageEvent) => void)[]> = {};
  addEventListener(t: string, f: (e: MessageEvent) => void) { (this.ls[t] ||= []).push(f); }
  close() { this.closed = true; }
  fire(t: string, data: unknown) { for (const f of this.ls[t] || []) f({ data: JSON.stringify(data) } as MessageEvent); }
}

const caps = (...devices: Array<[string, Array<[string, Array<string | null>]>]>): Capabilities => ({
  devices: devices.map(([device_id, cs]) => ({ device_id, connected: true, agent_version: "1.0", capabilities_version: 2, capabilities: cs.map(([provider, models]) => ({ provider: provider as "claude", models })) })),
});
const memory = (start: string | null = null): Saved & { v: string | null } => {
  const m = { v: start, get: () => m.v, set: (x: string) => { m.v = x; }, drop: () => { m.v = null; } };
  return m;
};
const grantOf = (over: Partial<Grant> = {}): Grant => ({ request_id: "r", device_id: "is_1", provider: "claude", model: "sonnet", state: "pending", prompt: "none", expires_at: "2026-11-10T09:05:00Z", connected: true, ...over });

function mk(active = true) {
  const s = new WebchatStore(), es = new FakeEs();
  s.saved = memory();
  s.sleep = async () => {};
  s.api = {
    sessions: vi.fn(async () => ({ sessions: active ? [{ session_id: "cs_1", status: "active", device_id: "is_1", connected: true, provider: "claude", model: "sonnet", binding_version: 2 }] : [] })),
    capabilities: vi.fn(async () => caps(["is_1", [["claude", ["sonnet", "opus"]], ["fake", [null]]]])),
    create: vi.fn(async (device_id: string, provider: string, model: string | null) => ({ session_id: "cs_2", status: "active", device_id, connected: true, provider, model, binding_version: 2 })),
    resume: vi.fn(async (id: string) => ({ session_id: id, status: "active", device_id: "is_1", connected: true, provider: "claude", model: "sonnet", binding_version: 2 })),
    grant: vi.fn(async (device_id: string, provider: string, model: string | null, request_id: string) => grantOf({ device_id, provider, model, request_id, created: true })),
    grantStatus: vi.fn(async (request_id: string) => grantOf({ request_id, state: "approved", prompt: "done" })),
    messages: vi.fn(async () => ({ messages: [] })),
    turn: vi.fn(async () => ({ turn_id: "ct_1", status: "running", created: true })),
    stop: vi.fn(async () => ({ turn_id: "ct_1" })),
    approvals: vi.fn(async () => ({ approvals: [] })),
    confirmApproval: vi.fn(async () => ({ status: "confirmed" as const, result: {} })),
    cancelApproval: vi.fn(async () => ({ status: "cancelled" as const })),
    stream: vi.fn(() => es),
  };
  return { s, es };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(r => { resolve = r; });
  return { promise, resolve };
}
const calls = (f: unknown) => (f as ReturnType<typeof vi.fn>).mock.calls;

test("열기 = 세션 하나 + SSE · 재생과 실시간이 겹쳐도 한 번 · 도구 호출 접힘 · 끝", async () => {
  const { s, es } = mk();
  await s.toggle(true);
  expect([s.open, s.sid, s.connected]).toEqual([true, "cs_1", true]);
  expect(s.api.stream).toHaveBeenCalledWith("cs_1");
  es.fire("turn", { turn_id: "ct_1", text: "안녕" });
  es.fire("turn", { turn_id: "ct_1", text: "안녕" });
  es.fire("delta", { turn_id: "ct_1", seq: 1, data: { text: "하나 " } });
  es.fire("delta", { turn_id: "ct_1", seq: 1, data: { text: "하나 " } });   // 같은 seq = 무시
  es.fire("tool_call", { turn_id: "ct_1", seq: 2, data: { name: "find", input: {} } });
  expect(s.running()).toBe(true);
  expect(s.canSend()).toBe(false);
  es.fire("tool_result", { turn_id: "ct_1", seq: 3, data: { name: "find", ok: true, summary: "3건" } });
  es.fire("delta", { turn_id: "ct_1", seq: 4, data: { text: "둘" } });
  es.fire("done", { turn_id: "ct_1", seq: 5, data: {} });
  const t = s.turns[0];
  expect(s.turns.length).toBe(1);
  expect([t.user, t.answer, t.end]).toEqual(["안녕", "하나 둘", "done"]);
  expect(t.tools).toEqual([{ name: "find", input: {}, ok: true, summary: "3건" }]);
  es.fire("pc", { connected: false });
  expect(s.connected).toBe(false);
  await s.toggle(false);
  await s.toggle(true);
  expect(s.api.sessions).toHaveBeenCalledTimes(1);   // 다시 열어도 같은 세션
});

test("active 대화 재개는 세션 목록을 거치고 새 세션을 만들지 않는다 · 고르기 버튼은 그 대화의 모델", async () => {
  const { s } = mk();
  await s.toggle(true);
  expect(s.api.resume).toHaveBeenCalledWith("cs_1");
  expect(s.api.create).not.toHaveBeenCalled();
  expect([s.provider, s.model, s.bindingVersion]).toEqual(["claude", "sonnet", 2]);
  expect(s.shown()).toEqual({ device: "is_1", provider: "claude", model: "sonnet" });
});

test("legacy active 세션은 재생할 수 있지만 새 턴은 보낼 수 없다", async () => {
  const { s } = mk();
  s.api.sessions = vi.fn(async () => ({ sessions: [{ session_id: "legacy", status: "active", device_id: "is_1", provider: "fake", model: null, binding_version: 0 }] }));
  await s.toggle(true);
  expect(s.api.resume).not.toHaveBeenCalled();
  expect(s.api.stream).toHaveBeenCalledWith("legacy");
  expect(s.readOnly).toBe(true);
  s.input = "새 턴";
  expect(s.canSend()).toBe(false);
});

test("초기 안내는 MyCRM 권한과 확인 규칙을 명시한다", () => {
  expect(EMPTY).toContain("MyCRM의 기존 권한과 확인 규칙을 따릅니다");
});

test("새 세션 충돌과 선택 공급자 미지원은 자동 대체 없이 원인을 알린다", () => {
  expect(errText({ code: "PROVIDER-UNAVAILABLE", msg: "" })).toContain("고른 AI 또는 모델");
  expect(errText({ code: "SESSION-CONFLICT", msg: "" })).toContain("다른 대화");
});

test("모델 고르기: 지난번 선택이 기본값 · 없으면 첫 항목 · 고르면 기억 · 사라진 선택은 버린다(목록이 비면 기억은 남긴다)", async () => {
  const { s } = mk(false);
  s.saved = memory("is_1|claude|opus");
  await s.toggle(true);
  expect(s.choice).toEqual({ device: "is_1", provider: "claude", model: "opus" });
  expect(s.choices().map(choiceKey)).toEqual(["is_1|claude|sonnet", "is_1|claude|opus", "is_1|fake|"]);
  s.pick({ device: "is_1", provider: "fake", model: null });
  expect([(s.saved as ReturnType<typeof memory>).v, s.pickerOpen]).toEqual(["is_1|fake|", false]);

  const gone = mk(false);
  gone.s.saved = memory("is_9|claude|old");
  await gone.s.toggle(true);
  expect([gone.s.choice?.model, (gone.s.saved as ReturnType<typeof memory>).v]).toEqual(["sonnet", null]);   // 없는 선택 = 버리고 첫 항목

  const off = mk(false);
  off.s.saved = memory("is_1|claude|opus");
  off.s.api.capabilities = vi.fn(async () => ({ devices: [] }));
  await off.s.toggle(true);
  expect([off.s.choice, (off.s.saved as ReturnType<typeof memory>).v, off.s.choices()]).toEqual([null, "is_1|claude|opus", []]);   // PC 꺼짐 = 기억 유지
  off.s.input = "x";
  expect(off.s.canSend()).toBe(false);
  expect(MODEL_KEY).toBe("mycrm-webchat-model");
});

test("모델 고르기: PC 가 둘이면 같은 목록에 PC 로 나뉜다 · 연결 끊긴 PC 는 빠진다", async () => {
  const { s } = mk(false);
  const c = caps(["is_1", [["claude", ["sonnet"]]]], ["is_2", [["claude", ["sonnet"]], ["codex", ["gpt-5"]]]], ["is_3", [["claude", ["x"]]]]);
  c.devices[2].connected = false;
  s.api.capabilities = vi.fn(async () => c);
  await s.toggle(true);
  expect(s.choices().map(choiceKey)).toEqual(["is_1|claude|sonnet", "is_2|claude|sonnet", "is_2|codex|gpt-5"]);
});

test("진행 중 대화에서 다른 모델 = 확인 뒤 새 대화(서버 세션 고정 그대로) · 취소 = 그대로 · 답이 도는 중이면 막는다", async () => {
  const { s, es } = mk();
  await s.toggle(true);
  es.fire("turn", { turn_id: "ct_1", text: "안녕" });
  es.fire("done", { turn_id: "ct_1", seq: 1, data: {} });
  s.togglePicker(true);
  s.pick({ device: "is_1", provider: "claude", model: "opus" });
  expect([s.pendingPick?.model, s.sid]).toEqual(["opus", "cs_1"]);
  s.togglePicker(false);
  expect([s.pendingPick, s.sid, s.choice?.model]).toEqual([null, "cs_1", "sonnet"]);
  s.togglePicker(true);
  s.pick({ device: "is_1", provider: "claude", model: "opus" });
  s.input = "초안";
  s.confirmPick();
  expect([s.sid, s.turns, s.choice?.model, s.input, es.closed, s.pickerOpen]).toEqual(["", [], "opus", "초안", true, false]);
  expect(s.api.create).not.toHaveBeenCalled();   // 새 대화는 첫 메시지 때 만든다
  s.pick({ device: "is_1", provider: "claude", model: "sonnet" });   // 대화가 없을 때 = 확인 없이 바로
  expect([s.pendingPick, s.choice?.model]).toEqual([null, "sonnet"]);

  const run = mk();
  await run.s.toggle(true);
  run.es.fire("turn", { turn_id: "ct_1", text: "안녕" });
  run.s.pick({ device: "is_1", provider: "fake", model: null });
  run.s.confirmPick();
  expect([run.s.sid, run.s.bad]).toEqual(["cs_1", true]);
});

test("첫 메시지 = 고른 모델로 시작 · fake 는 허용 없이 바로 세션, 그 글을 보낸다", async () => {
  const { s } = mk(false);
  await s.toggle(true);
  s.pick({ device: "is_1", provider: "fake", model: null });
  s.input = "처음";
  expect(s.canSend()).toBe(true);
  await s.send();
  expect(s.api.grant).not.toHaveBeenCalled();
  expect(calls(s.api.create)[0].slice(0, 3)).toEqual(["is_1", "fake", null]);
  expect(calls(s.api.turn)[0].slice(0, 2)).toEqual(["cs_2", "처음"]);
  expect([s.sid, s.input]).toEqual(["cs_2", ""]);
});

test("PC 허용: 요청 → 대기(창 뜸) → 허용 = 같은 id 로 세션 → 보내려던 글을 보낸다", async () => {
  const { s } = mk(false);
  await s.toggle(true);
  s.input = "질문";
  const seen: string[] = [];
  s.api.grantStatus = vi.fn().mockResolvedValueOnce(grantOf({ prompt: "open" })).mockResolvedValueOnce(grantOf({ state: "approved", prompt: "done" }));
  s.sleep = async () => { seen.push(s.grantNote); };
  await s.send();
  const rid = calls(s.api.grant)[0][3];
  expect(calls(s.api.grant)[0].slice(0, 3)).toEqual(["is_1", "claude", "sonnet"]);
  expect(seen).toEqual(["none", "open"]);
  expect(calls(s.api.grantStatus).map(c => c[0])).toEqual([rid, rid]);
  expect(calls(s.api.create)[0]).toEqual(["is_1", "claude", "sonnet", rid]);   // client_session_id = 허용 요청 id
  expect(calls(s.api.turn)[0].slice(0, 2)).toEqual(["cs_2", "질문"]);
  expect([s.grantNote, s.grant, s.input]).toEqual(["", null, ""]);
});

test("PC 허용 대기 중엔 입력을 잠근다 · 그만 기다리기 = 세션 없음, 글은 남는다", async () => {
  const { s } = mk(false);
  await s.toggle(true);
  s.input = "질문";
  const gate = deferred<void>();
  s.sleep = () => gate.promise;
  const p = s.send();
  await Promise.resolve(); await Promise.resolve();
  expect([s.waiting(), s.canSend()]).toEqual([true, false]);
  s.cancelGrant();
  gate.resolve();
  await p;
  expect([s.grantNote, s.sid, s.input]).toEqual(["", "", "질문"]);
  expect(s.api.create).not.toHaveBeenCalled();
});

test("PC 허용 끝: 창 닫힘(취소, 응답 없음) · 시간 초과 · PC 꺼짐 = 각자 표시, 세션을 만들지 않는다 · 다시 요청 = 새 id", async () => {
  for (const [st, note] of [[{ prompt: "closed" as const }, "closed"], [{ state: "expired" as const }, "expired"], [{ connected: false }, "offline"]] as const) {
    const { s } = mk(false);
    await s.toggle(true);
    s.input = "질문";
    s.api.grantStatus = vi.fn(async () => grantOf(st));
    await s.send();
    expect([s.grantNote, s.sid, s.input, s.waiting()]).toEqual([note, "", "질문", false]);
    expect(s.api.create).not.toHaveBeenCalled();
    s.api.grantStatus = vi.fn(async (request_id: string) => grantOf({ request_id, state: "approved", prompt: "done" }));
    await s.retryGrant();
    const [first, second] = calls(s.api.grant).map(c => c[3]);
    expect(first).not.toBe(second);
    expect(calls(s.api.create)[0][3]).toBe(second);
    expect(calls(s.api.turn)[0].slice(0, 2)).toEqual(["cs_2", "질문"]);
  }
});

test("PC 앱이 허용하지 않음을 알리면(prompt declined) 폴링을 멈추고 declined 로 끝낸다 · 세션을 만들지 않는다", async () => {
  const { s } = mk(false);
  await s.toggle(true);
  s.input = "질문";
  s.api.grantStatus = vi.fn(async () => grantOf({ prompt: "declined" }));
  await s.send();
  expect([s.grantNote, s.sid, s.input, s.waiting()]).toEqual(["declined", "", "질문", false]);
  expect(s.api.grantStatus).toHaveBeenCalledTimes(1);
  expect(s.api.create).not.toHaveBeenCalled();
});

test("허용 요청 실패와 세션 생성 실패는 문구로 알리고 글을 남긴다", async () => {
  const { s } = mk(false);
  await s.toggle(true);
  s.input = "질문";
  s.api.grant = vi.fn(async () => { throw new ApiFail({ code: "NOT-FOUND", msg: "그 장치를 찾을 수 없어요." }); });
  await s.send();
  expect([s.grantNote, s.line, s.bad, s.input]).toEqual(["", "그 장치를 찾을 수 없어요.", true, "질문"]);
  s.api.grant = vi.fn(async (...a: [string, string, string | null, string]) => grantOf({ request_id: a[3] }));
  s.api.create = vi.fn(async () => { throw new ApiFail({ code: "GRANT-EXPIRED", msg: "" }); });
  await s.send();
  expect([s.sid, s.line, s.input]).toEqual(["", ERR["GRANT-EXPIRED"], "질문"]);
});

test("기존 세션의 턴 CONSENT_REQUIRED = 허용이 끝났다고 알리고 다시 요청하지 않는다 · 입력 보존", async () => {
  const { s } = mk();
  await s.toggle(true);
  s.input = "질문";
  s.api.turn = vi.fn(async () => { throw new ApiFail({ code: "CONSENT_REQUIRED", msg: "" }); });
  await s.send();
  expect([s.line, s.bad, s.sid, s.input]).toEqual([ERR.CONSENT_REQUIRED, true, "cs_1", "질문"]);
  expect(s.api.grant).not.toHaveBeenCalled();
  expect(ERR.CONSENT_REQUIRED).toContain("새 대화");
});

test("보내기 — client_turn_id 를 싣고 성공하면 입력 비움 · 중지 · 오류 = 문구 · 세션 끝 = 빈 새 대화", async () => {
  const { s, es } = mk();
  await s.toggle(true);
  s.input = "질문";
  expect(s.canSend()).toBe(true);
  await s.send();
  const [sid, text, ctid] = calls(s.api.turn)[0];
  expect([sid, text, typeof ctid, String(ctid).length > 8]).toEqual(["cs_1", "질문", "string", true]);
  expect(s.input).toBe("");
  es.fire("turn", { turn_id: "ct_1", text: "질문" });
  await s.stop();
  expect(s.api.stop).toHaveBeenCalledWith("cs_1");
  es.fire("error", { turn_id: "ct_1", seq: 1, data: { code: "STOPPED" } });
  expect([s.turns[0].end, s.turns[0].endNote]).toEqual(["error", END.STOPPED]);
  s.input = "x".repeat(TEXT_MAX + 1);
  expect(s.canSend()).toBe(false);
  s.input = "다음";
  s.api.turn = vi.fn(async () => { throw new ApiFail({ code: "DEVICE-GONE", msg: "" }); });
  await s.send();
  expect([s.line, s.bad, s.sid, s.input, s.turns]).toEqual([ERR["DEVICE-GONE"], true, "", "다음", []]);
  s.close();
  expect(es.closed).toBe(true);
});

test("다른 탭에서 열림 = SSE 닫고 다시 붙지 않음 · 다시 열면 이어 받기 · 생략 안내 · 다른 PC 의 pc 이벤트 무시", async () => {
  const { s, es } = mk();
  await s.toggle(true);
  es.fire("trimmed", { first_turn_id: "ct_9" });
  expect(s.trimmed).toBe(TRIMMED);
  es.fire("pc", { device_id: "is_other", connected: false });
  expect(s.connected).toBe(true);   // 이 대화의 PC(is_1)가 아님
  es.fire("pc", { device_id: "is_1", connected: false });
  expect(s.connected).toBe(false);
  es.fire("pc", { device_id: "is_1", connected: true });
  s.input = "x";
  es.fire("replaced", {});
  expect([es.closed, s.replaced, s.line, s.canSend()]).toEqual([true, true, REPLACED, false]);
  await s.toggle(false);
  await s.toggle(true);
  expect(s.api.stream).toHaveBeenCalledTimes(2);
  expect([s.replaced, s.line, s.trimmed]).toEqual([false, "", ""]);
});

test("지난 대화: 목록 = 세션 목록 · 끝난 대화 = messages 로 읽기 전용 · 지금 대화 = 이어 받기 · 새 대화로 돌아오기", async () => {
  const { s } = mk();
  await s.toggle(true);
  const past = { session_id: "cs_0", status: "closed", device_id: "is_1", provider: "claude", model: "opus", binding_version: 2, created_at: "2026-11-09T01:00:00Z" };
  s.api.sessions = vi.fn(async () => ({ sessions: [{ session_id: "cs_1", status: "active", device_id: "is_1", provider: "claude", model: "sonnet", binding_version: 2 }, past] }));
  s.api.messages = vi.fn(async () => ({ messages: [
    { id: "m1", turn_id: "ct_a", role: "user" as const, body: "예전 질문", created_at: "", turn_status: "done" },
    { id: "m2", turn_id: "ct_a", role: "assistant" as const, body: "예전 답", created_at: "", turn_status: "done" },
    { id: "m3", turn_id: "ct_b", role: "user" as const, body: "멈춘 질문", created_at: "", turn_status: "stopped" },
  ] }));
  await s.openHistory(true);
  expect([s.view, s.past.map(p => p.session_id)]).toEqual(["history", ["cs_1", "cs_0"]]);
  await s.openPast(past);
  expect(s.api.messages).toHaveBeenCalledWith("cs_0");
  expect([s.view, s.sid, s.readOnly, s.model]).toEqual(["chat", "cs_0", true, "opus"]);
  expect(s.turns.map(t => [t.user, t.answer, t.end])).toEqual([["예전 질문", "예전 답", "done"], ["멈춘 질문", "", "error"]]);
  s.input = "이어서";
  expect(s.canSend()).toBe(false);
  expect(s.api.approvals).toHaveBeenCalledTimes(1);   // 지난 대화는 확인 카드를 다시 부르지 않는다(열 때 1번은 지금 대화)
  await s.openPast(s.past[0]);
  expect([s.sid, s.readOnly]).toEqual(["cs_1", false]);
  expect(s.api.resume).toHaveBeenLastCalledWith("cs_1");
  s.newChat();
  expect([s.sid, s.readOnly, s.turns, s.view]).toEqual(["", false, [], "chat"]);
});

test("pastTurns: turn_status 끝 문구 · 사용자 글만 있는 턴", () => {
  const t = pastTurns([{ id: "m", turn_id: "ct", role: "user", body: "a", created_at: "", turn_status: "failed" }]);
  expect([t[0].end, t[0].endNote, t[0].answer]).toEqual(["error", "답이 끝나지 못했어요.", ""]);
});

test("승인 목록은 세션에 묶어 조회하고 pending만 보관한다", async () => {
  const { s } = mk();
  s.api.approvals = vi.fn(async () => ({ approvals: [
    { id: "ap_1", turn_id: "ct_1", op: "create", params: { nested: { all: ["x", "y"] } }, shown: { label: "표시" }, impact: { count: 1 }, irreversible: true, status: "pending" as const, created_at: "2026-11-08T00:00:00Z", expires_at: "2026-11-08T00:05:00Z", finished_at: null, result: null },
    { id: "ap_old", turn_id: "ct_0", op: "delete", params: {}, shown: {}, impact: {}, irreversible: false, status: "cancelled" as const, created_at: "", expires_at: "", finished_at: "2026-11-08T00:01:00Z", result: null },
  ] }));
  await s.toggle(true);
  expect(s.api.approvals).toHaveBeenCalledWith("cs_1");
  expect(s.approvals.map(a => a.id)).toEqual(["ap_1", "ap_old"]);
});

test("승인 확인과 취소는 본문 없는 명시 endpoint를 호출하고 목록을 다시 받는다", async () => {
  const { s } = mk();
  await s.toggle(true);
  s.approvals = [{ id: "ap_1", turn_id: "ct_1", op: "update", params: {}, shown: {}, impact: {}, irreversible: false, status: "pending", created_at: "", expires_at: "", finished_at: null, result: null }];
  await s.actOnApproval("ap_1", "confirm");
  expect(s.api.confirmApproval).toHaveBeenCalledWith("cs_1", "ap_1");
  expect(s.approvalLine).toBe("요청을 확인했어요.");
  s.approvals = [{ ...s.approvals[0], id: "ap_2", status: "pending" }];
  await s.actOnApproval("ap_2", "cancel");
  expect(s.api.cancelApproval).toHaveBeenCalledWith("cs_1", "ap_2");
  expect(s.approvalLine).toBe("요청을 취소했어요.");
  expect(s.api.approvals).toHaveBeenCalledTimes(3);
});

test("승인 실패는 이유를 알리고 재조회해 만료·중복 대기 카드를 제거한다", async () => {
  const { s } = mk();
  await s.toggle(true);
  s.approvals = [{ id: "ap_1", turn_id: "ct_1", op: "edit", params: {}, shown: {}, impact: {}, irreversible: false, status: "pending", created_at: "", expires_at: "", finished_at: null, result: null }];
  s.api.confirmApproval = vi.fn(async () => { throw new ApiFail({ code: "EXPIRED", msg: "요청이 만료됐어요.", status: 409 }); });
  s.api.approvals = vi.fn(async () => ({ approvals: [] }));
  await s.actOnApproval("ap_1", "confirm");
  expect([s.approvals, s.approvalLine, s.approvalBad]).toEqual([[], "요청이 만료됐어요.", true]);
});

test("세션이 바뀌면 이전 승인 조회 응답은 새 세션 카드에 덮어쓰지 않는다", async () => {
  const { s, es } = mk();
  const old = deferred<{ approvals: import("./api").Approval[] }>();
  const current = { id: "ap_new", turn_id: "ct_2", op: "new", params: {}, shown: {}, impact: {}, irreversible: false, status: "pending" as const, created_at: "", expires_at: "", finished_at: null, result: null };
  s.api.approvals = vi.fn().mockReturnValueOnce(old.promise).mockResolvedValue({ approvals: [current] });
  await s.toggle(true);
  expect(s.sid).toBe("cs_1");
  es.fire("turn", { turn_id: "ct_1", text: "a" }); es.fire("done", { turn_id: "ct_1", seq: 1, data: {} });
  s.pick({ device: "is_1", provider: "fake", model: null }); s.confirmPick();
  s.input = "새로";
  await s.send();
  await Promise.resolve();
  expect([s.sid, s.approvals.map(a => a.id)]).toEqual(["cs_2", ["ap_new"]]);
  old.resolve({ approvals: [{ ...current, id: "ap_old", turn_id: "ct_1" }] });
  await old.promise;
  await Promise.resolve();
  expect([s.sid, s.approvals.map(a => a.id)]).toEqual(["cs_2", ["ap_new"]]);
});

test("세션이 바뀌면 이전 확인 결과와 오류는 새 세션에 표시하지 않는다", async () => {
  const { s } = mk();
  await s.toggle(true);
  s.approvals = [{ id: "ap_1", turn_id: "ct_1", op: "update", params: {}, shown: {}, impact: {}, irreversible: false, status: "pending", created_at: "", expires_at: "", finished_at: null, result: null }];
  const old = deferred<{ status: "confirmed"; result: Record<string, unknown> }>();
  s.api.confirmApproval = vi.fn(() => old.promise);
  const action = s.actOnApproval("ap_1", "confirm");
  s.newChat();
  s.pick({ device: "is_1", provider: "fake", model: null });
  s.input = "새로";
  await s.send();
  expect([s.sid, s.approvals, s.approvalAction, s.approvalLine, s.approvalResult]).toEqual(["cs_2", [], "", "", null]);
  old.resolve({ status: "confirmed", result: { private: "old-session-result" } });
  await action;
  expect([s.sid, s.approvalLine, s.approvalBad, s.approvalResult]).toEqual(["cs_2", "", false, null]);
});

test("기본 저장소 = 브라우저 localStorage 의 모델 선택 하나 · 새 창(새 store)이 그 선택을 기본값으로 쓴다 · 첫 메시지 두 번 = 세션 하나", async () => {
  localStorage.removeItem(MODEL_KEY);
  const a = mk(false);
  a.s.saved = new WebchatStore().saved;   // 주입 없는 기본 어댑터
  await a.s.toggle(true);
  a.s.pick({ device: "is_1", provider: "claude", model: "opus" });
  expect(localStorage.getItem(MODEL_KEY)).toBe("is_1|claude|opus");
  const b = mk(false);
  b.s.saved = new WebchatStore().saved;
  await b.s.toggle(true);
  expect(b.s.choice).toEqual({ device: "is_1", provider: "claude", model: "opus" });
  b.s.pick({ device: "is_1", provider: "fake", model: null });
  b.s.input = "한 번";
  await Promise.all([b.s.send(), b.s.send()]);
  expect([calls(b.s.api.create).length, calls(b.s.api.turn).length]).toEqual([1, 1]);
  localStorage.removeItem(MODEL_KEY);
});

test("확인 카드 값 표현: 참거짓과 숫자는 서버 값 그대로 글자로(바꿔 말하지 않는다)", async () => {
  const { Shown } = await import("./ApprovalCard");
  const { createRoot } = await import("react-dom/client");
  const { act } = await import("react");
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  const el = document.createElement("div"); document.body.append(el);
  const root = createRoot(el);
  act(() => root.render(Shown({ v: { "바꿀 검토": true, "지금 revision": 3, "사유": "" } })));
  expect(el.textContent).toContain("true");
  expect(el.textContent).toContain("3");
  expect(el.textContent).toContain("빈 값");
  act(() => root.unmount()); el.remove();
});
