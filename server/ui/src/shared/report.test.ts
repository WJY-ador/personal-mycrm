// 오류 자동 보고(shared/report) — 단계 = 주소의 낱말 조각만(id 없음) · 같은 (단계, 코드)는 횟수로 한 번 · 5xx 만 보낸다 · 꼴이 틀린 단계는 보내지 않는다
import { afterEach, expect, test, vi } from "vitest";
import { ApiFail, getJSON } from "./api";
import { _flushNow, osKind, reportError, stageOf } from "./report";

afterEach(() => { vi.unstubAllGlobals(); });

test("stageOf — id 와 숫자 섞인 조각을 버리고 앞의 낱말 둘까지", () => {
  expect(stageOf("/api/chat/sessions/cs_1a2b/turns")).toBe("api/chat/sessions");
  expect(stageOf("/api/state")).toBe("api/state");
  expect(stageOf("/api/people/p_123/context?x=1")).toBe("api/people/context");
  expect(osKind("Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0)")).toBe("mac");
  expect(osKind("Mozilla/5.0 (Windows NT 10.0)")).toBe("win");
});

test("같은 (단계, 코드)는 모아 횟수로 한 번, 본문엔 코드와 고정 낱말만", async () => {
  const sent: Record<string, unknown>[] = [];
  vi.stubGlobal("fetch", vi.fn(async (_u: string, init: RequestInit) => { sent.push(JSON.parse(String(init.body))); return new Response("{}"); }));
  reportError("chat/turn", "TURN-TIMEOUT");
  reportError("chat/turn", "TURN-TIMEOUT");
  reportError("chat/turn", "연결 실패 문장");   // 코드 꼴이 아니면 unknown
  reportError("C:/Users/x", "HTTP-500");        // 단계 꼴이 아니면 보내지 않는다
  _flushNow();
  expect(sent.map(b => [b.stage, b.code, b.count, b.source, b.app_version])).toEqual([["chat/turn", "TURN-TIMEOUT", 2, "web", ""], ["chat/turn", "unknown", 1, "web", ""]]);
  expect(String(sent[0].occurred_at)).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/);
});

test("API 5xx 는 자동 보고, 4xx 는 보내지 않는다", async () => {
  const sent: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (u: string, init?: RequestInit) => {
    if (u === "/api/error-reports") { sent.push(JSON.parse(String(init!.body)).code); return new Response("{}"); }
    return new Response(JSON.stringify({ code: "X" }), { status: u.includes("bad") ? 400 : 503 });
  }));
  await expect(getJSON("/api/state")).rejects.toBeInstanceOf(ApiFail);
  await expect(getJSON("/api/bad")).rejects.toBeInstanceOf(ApiFail);
  _flushNow();
  expect(sent).toEqual(["HTTP-503"]);
});
