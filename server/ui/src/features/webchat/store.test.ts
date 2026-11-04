// 웹 「대화」 상태 — 가짜 서버 접점·가짜 EventSource 로 흐름 단위: 열기 = 세션 + SSE · 재생/실시간 겹침 1번 · 도구 접힘 · 끝 상태 · 보내기 멱등 키 · 오류 문구.
import { expect, test, vi } from "vitest";
import { ApiFail } from "../../shared/api";
import type { Es } from "./api";
import { WebchatStore } from "./store";
import { END, ERR, REPLACED, TEXT_MAX, TRIMMED } from "./text";

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
    open: vi.fn(async () => ({ session_id: "cs_1", status: "active", device_id: "is_1", connected: true })),
    turn: vi.fn(async () => ({ turn_id: "ct_1", status: "running", created: true })),
    stop: vi.fn(async () => ({ turn_id: "ct_1" })),
    stream: vi.fn(() => es),
  };
  return { s, es };
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
  expect(s.api.open).toHaveBeenCalledTimes(1);   // 다시 열어도 같은 세션
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
  s.api.open = vi.fn(async () => { throw new ApiFail({ code: "NO-DEVICE", msg: "" }); });
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
