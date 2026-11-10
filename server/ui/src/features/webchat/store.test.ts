// 웹 「대화」 상태 — 가짜 서버 접점·가짜 EventSource 로 흐름 단위: 열기 = 세션 + SSE · 재생/실시간 겹침 1번 · 도구 접힘 · 끝 상태 · 보내기 멱등 키 · 오류 문구.
import { expect, test, vi } from "vitest";
import { ApiFail } from "../../shared/api";
import type { Es } from "./api";
import { WebchatStore } from "./store";
import { EMPTY, END, ERR, REPLACED, TEXT_MAX, TRIMMED, errText } from "./text";

class FakeEs implements Es {
  onmessage = null; onerror = null; closed = false;
  ls: Record<string, ((e: MessageEvent) => void)[]> = {};
  addEventListener(t: string, f: (e: MessageEvent) => void) { (this.ls[t] ||= []).push(f); }
  close() { this.closed = true; }
  fire(t: string, data: unknown) { for (const f of this.ls[t] || []) f({ data: JSON.stringify(data) } as MessageEvent); }
}

function mk() {
  const s = new WebchatStore(), es = new FakeEs();
  s.api = {
    sessions: vi.fn(async () => ({ sessions: [{ session_id: "cs_1", status: "active", device_id: "is_1", connected: true, provider: "claude", model: "sonnet", binding_version: 2 }] })),
    capabilities: vi.fn(async () => ({ devices: [{ device_id: "is_1", connected: true, agent_version: "1.0", capabilities_version: 2, capabilities: [{ provider: "claude" as const, models: ["sonnet"] }] }] })),
    create: vi.fn(async () => ({ session_id: "cs_2", status: "active", device_id: "is_1", connected: true, provider: "claude", model: "sonnet", binding_version: 2 })),
    resume: vi.fn(async (id: string) => ({ session_id: id, status: "active", device_id: "is_1", connected: true, provider: "claude", model: "sonnet", binding_version: 2 })),
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

test("active 대화 재개는 authenticated 세션 목록을 거치고 새 세션을 만들지 않는다", async () => {
  const { s } = mk();
  await s.toggle(true);
  expect(s.api.resume).toHaveBeenCalledWith("cs_1");
  expect(s.api.create).not.toHaveBeenCalled();
  expect([s.provider, s.model, s.bindingVersion]).toEqual(["claude", "sonnet", 2]);
});

test("active 세션이 없으면 capability를 표시하고 사용자가 선택한 뒤에만 신규 생성한다", async () => {
  const { s } = mk();
  s.api.sessions = vi.fn(async () => ({ sessions: [] }));
  await s.toggle(true);
  expect(s.selectorOpen).toBe(true);
  expect(s.api.capabilities).toHaveBeenCalledTimes(1);
  expect(s.api.create).not.toHaveBeenCalled();
  await s.createSession("is_1", "claude", "sonnet");
  expect(s.api.create).toHaveBeenCalledWith("is_1", "claude", "sonnet", expect.any(String));
  expect([s.sid, s.provider, s.model, s.bindingVersion]).toEqual(["cs_2", "claude", "sonnet", 2]);
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

test("초기 안내는 MyCRM 도구별 권한과 확인 규칙을 명시한다", () => {
  expect(EMPTY).toContain("MyCRM 작업은 기존 도구 권한과 확인 규칙을 따릅니다");
});

test("Codex 로그인이 필요하면 PC 설정에서 로그인 후 재시도하도록 안내한다", async () => {
  const { s, es } = mk();
  await s.toggle(true);
  es.fire("turn", { turn_id: "ct_1", text: "질문" });
  es.fire("error", { turn_id: "ct_1", seq: 1, data: { code: "CODEX-LOGIN-REQUIRED" } });
  expect(s.turns[0].endNote).toBe("PC 앱 설정에서 Codex에 로그인한 뒤 다시 시도하세요.");
  expect(s.turns[0].endNote).not.toContain("CODEX-LOGIN-REQUIRED");
});

test("새 세션 충돌과 선택 공급자 미지원은 자동 대체 없이 원인을 알린다", () => {
  expect(errText({ code: "PROVIDER-UNAVAILABLE", msg: "" })).toContain("선택한 AI 또는 모델");
  expect(errText({ code: "SESSION-CONFLICT", msg: "" })).toContain("다른 대화");
});

test("미전송 초안이 있으면 새 세션 전환을 막고 초안을 보존한다", async () => {
  const { s } = mk();
  await s.toggle(true);
  s.capabilities = { devices: [{ device_id: "is_1", connected: true, agent_version: "1.0", capabilities_version: 2, capabilities: [{ provider: "claude", models: ["sonnet"] }] }] };
  s.input = "작성 중인 초안";
  await s.newConversation();
  expect([s.input, s.selectorOpen]).toEqual(["작성 중인 초안", false]);
  await s.createSession("is_1", "claude", "sonnet");
  expect(s.input).toBe("작성 중인 초안");
  expect(s.api.create).not.toHaveBeenCalled();
});

test("CONSENT_REQUIRED는 PC 허용 절차 미구현 상태를 표시하고 다른 공급자로 대체하지 않는다", async () => {
  const { s } = mk();
  s.api.sessions = vi.fn(async () => ({ sessions: [] }));
  await s.toggle(true);
  s.api.create = vi.fn(async () => { throw new ApiFail({ code: "CONSENT_REQUIRED", msg: "" }); });
  await s.createSession("is_1", "claude", "sonnet");
  expect(s.api.create).toHaveBeenCalledTimes(1);
  expect([s.sid, s.selectorOpen, s.line, s.bad]).toEqual(["", true, ERR.CONSENT_REQUIRED, true]);
  expect(errText({ code: "CONSENT_REQUIRED", msg: "" })).toContain("PC에서 이 대화를 허용하는 절차가 아직 준비되지 않아 현재는 사용할 수 없어요");
});

test("기존 세션의 턴도 CONSENT_REQUIRED를 그대로 표시하고 입력을 보존한다", async () => {
  const { s } = mk();
  await s.toggle(true);
  s.input = "질문";
  s.api.turn = vi.fn(async () => { throw new ApiFail({ code: "CONSENT_REQUIRED", msg: "" }); });
  await s.send();
  expect([s.line, s.bad, s.sid, s.input]).toEqual([ERR.CONSENT_REQUIRED, true, "cs_1", "질문"]);
});

test("보내기 — client_turn_id 를 싣고 성공하면 입력 비움 · 중지 · 오류 = 문구 · 세션 끝 = 다시 열 때 새 세션", async () => {
  const { s, es } = mk();
  await s.toggle(true);
  s.input = "질문";
  expect(s.canSend()).toBe(true);
  await s.send();
  const [sid, text, ctid] = (s.api.turn as ReturnType<typeof vi.fn>).mock.calls[0];
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
  expect([s.line, s.bad, s.sid, s.input]).toEqual([ERR["DEVICE-GONE"], true, "", "다음"]);
  s.sid = "";
  s.api.sessions = vi.fn(async () => { throw new ApiFail({ code: "NO-DEVICE", msg: "" }); });
  await s.toggle(false);
  await s.toggle(true);
  expect(s.line).toBe(ERR["NO-DEVICE"]);
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
  const { s } = mk();
  const old = deferred<{ approvals: import("./api").Approval[] }>();
  const current = { id: "ap_new", turn_id: "ct_2", op: "new", params: {}, shown: {}, impact: {}, irreversible: false, status: "pending" as const, created_at: "", expires_at: "", finished_at: null, result: null };
  s.api.approvals = vi.fn().mockReturnValueOnce(old.promise).mockResolvedValue({ approvals: [current] });
  await s.toggle(true);
  expect(s.sid).toBe("cs_1");
  s.capabilities = { devices: [{ device_id: "is_1", connected: true, agent_version: "1.0", capabilities_version: 2, capabilities: [{ provider: "claude", models: ["sonnet"] }] }] };
  await s.createSession("is_1", "claude", "sonnet");
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
  s.capabilities = { devices: [{ device_id: "is_1", connected: true, agent_version: "1.0", capabilities_version: 2, capabilities: [{ provider: "claude", models: ["sonnet"] }] }] };
  await s.createSession("is_1", "claude", "sonnet");
  expect([s.sid, s.approvals, s.approvalAction, s.approvalLine, s.approvalResult]).toEqual(["cs_2", [], "", "", null]);
  old.resolve({ status: "confirmed", result: { private: "old-session-result" } });
  await action;
  expect([s.sid, s.approvalLine, s.approvalBad, s.approvalResult]).toEqual(["cs_2", "", false, null]);
});
