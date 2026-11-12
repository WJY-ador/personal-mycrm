// 대화 저장소(흐름) — 옛 test_web_home.py test_static_chat·test_chat_restore_offline·test_chat_nodev_session 의 흐름 단언을 옮김(R3).
import { expect, test, vi } from "vitest";
import { mdhm } from "../../shared/date";
import storeSrc from "./store.ts?raw";
import { mk, NODEV, pv, st, T } from "../../test/chat";

const all = import.meta.glob(["../../**/*.{ts,tsx}", "!../../**/*.test.{ts,tsx}", "!../../test/**"], { query: "?raw", import: "default", eager: true }) as Record<string, string>;

test("서버 접점 한 곳 — 작업·쌓기 API 는 chatApi 밖에서 부르지 않는다 · 브라우저 저장소 0 · 고정 문구 한 곳", () => {
  const hits = Object.entries(all).filter(([p, s]) => !/(^\.\/|\/chat\/)chatApi\.ts$/.test(p) && /\/api\/(jobs|stack\/)/.test(s)).map(([p]) => p);
  expect(hits).toEqual([]);
  expect(storeSrc).not.toMatch(/Storage/);
  expect(Object.values(all).filter(s => s.includes(NODEV)).length).toBe(1);
  expect(Object.values(all).join("\n")).not.toContain("실행 가능");
});

test("새 턴 — 원문으로 저장 = 세션 첫 입력만 · 8,000자(코드포인트) · 접수 뒤 롱폴은 같은 작업에 하나", async () => {
  const s = mk(); s.sync(st({ devices_status: { state: "recent", last_seen_at: null, threshold_seconds: 180 } }), async () => {});
  s.input = "가".repeat(8001); expect(s.canSend()).toBe(false);
  s.input = "😀".repeat(8000); expect(s.canSend()).toBe(true);
  s.input = "첫 말"; s.verbatim = true; await s.send();
  expect(s.api.send).toHaveBeenLastCalledWith({ kind: "converse", text: "첫 말", input_kind: "verbatim" });
  expect([s.sid, s.kind, s.turns, s.input]).toEqual(["s1", "verbatim", ["첫 말"], ""]);
  s.input = "다음 말"; await s.send();
  expect(s.api.send).toHaveBeenLastCalledWith({ kind: "converse", text: "다음 말", session_id: "s1" });
  void s.wait("jx"); void s.wait("jx");
  expect(s.api.poll).toHaveBeenCalledTimes(1);   // 같은 작업 롱폴 겹침 0
});

test("최신 결과만 — 다른 작업 결과·고치는 중 도착 = 버림 · latest=false = 확정 불가 · 막힌 질문 = 확정 잠금(서버 blocked_open 우선)", () => {
  const s = mk(); s.sync(st(), async () => {});
  s.want = "j2";
  expect(s.show(pv(), "j1", "r1")).toBe(false);
  expect(s.show(pv({ latest: false }), "j2", "r1")).toBe(true);
  expect([s.canConfirm(), s.line]).toEqual([false, "이 결과는 최신이 아니에요. 최신 결과를 기다려 주세요."]);
  s.show(pv({ blocked_open: true }), "j2", "r1"); expect(s.canConfirm()).toBe(false);
  s.show(pv({ blocked: [{ cid: null, code: "x", question: "누구?" }] }), "j2", "r1"); expect(s.canConfirm()).toBe(false);
  s.show(pv(), "j2", "r1"); expect(s.canConfirm()).toBe(true);
  s.edit("u1", "하나 고침");
  expect([s.dirty, s.canConfirm(), s.line]).toEqual([true, false, "고친 글은 입력 칸을 벗어나면 다시 정리해요."]);
  expect(s.show(pv({ id: "p9" }), "j2", "r1")).toBe(false);
  expect(s.api.send).not.toHaveBeenCalled();   // 입력 = 잠금만(요청 0)
});

test("재정리 = 구조(원 결과·편집 세대·고친 글·뺀 변경·막힘 답) · 세대는 접수됐을 때만 올림 · 확정 요청 ID = 미리보기당 1(재시도 재사용)", async () => {
  const s = mk(); s.sync(st(), async () => {}); s.sid = "s1"; s.want = "j1";
  s.show(pv({ excluded: ["c9"], edit_generation: 2 }), "j1", "r1");
  s.edit("u2", "둘 고침"); s.leave();
  await vi.waitFor(() => expect(s.api.send).toHaveBeenCalledTimes(1));
  expect(s.api.send).toHaveBeenLastCalledWith({ kind: "converse", session_id: "s1", text: "하나\n\n둘 고침",
    restack: { parent_result_version: "r1", edit_generation: 3, edited_text: "하나\n\n둘 고침", excluded_cids: ["c9"] } });
  await vi.waitFor(() => expect(s.gen).toBe(3));
  s.api.send = vi.fn(async () => ({ ok: false as const, status: 409, code: "JOB-LIMIT", msg: "" }));
  s.want = "j2"; s.show(pv({ id: "p2", blocked: [{ cid: null, code: "x", question: "누구?" }, { cid: null, code: "x", question: "언제?" }] }), "j2", "r1");
  s.setAnswer(0, " 나 "); s.setAnswer(1, ""); s.answer();
  await vi.waitFor(() => expect(s.line).toBe("진행 중인 작업이 많아요. 끝난 뒤 다시 보내 주세요."));
  expect((s.api.send as ReturnType<typeof vi.fn>).mock.calls[0][0].restack.answers).toEqual([{ cid: null, text: "나" }]);
  expect(s.gen).toBe(3);
  const s2 = mk(); s2.sync(st(), async () => {}); s2.want = "j1"; s2.show(pv(), "j1", "r1");
  s2.api.confirm = vi.fn(async () => ({ ok: false as const, status: 0, code: "OFFLINE", msg: "" }));
  await s2.confirm(); await s2.confirm();
  const ids = (s2.api.confirm as ReturnType<typeof vi.fn>).mock.calls.map(c => c[1].request_id);
  expect(ids[0]).toBe(ids[1]);
  expect(s2.line).toBe("연결이 끊겼어요. 다시 [확정]을 누르면 같은 요청으로 다시 보내요(두 번 저장되지 않아요).");
  expect((s2.api.confirm as ReturnType<typeof vi.fn>).mock.calls[0]).toEqual(["j1", { request_id: ids[0], preview_id: "p1", preview_version: 1, preview_sha: "h1" }]);
});

test("새로 고침 복원 — 기다리는 작업: 오프라인 = 첫 롱폴 전 PC 대기 문구(대기·실행 중) · 최근 연결 = 「정리하고 있어요…」", async () => {
  const go = async (state: string, status: string) => {
    const s = mk(); s.S = st({ devices_status: { state, last_seen_at: T, threshold_seconds: 180 } }); s.sid = "s9";
    s.api.session = vi.fn(async () => ({ ok: true as const, j: { session_id: "s9", input_kind: "converse", expires_at: "2099-01-01T00:00:00+00:00", edit_generation: 0,
      latest_job: { id: "j-" + state + status, status }, preview: null, confirmed: false } }));
    return [await s.restore("s9"), s.line];
  };
  const off = `PC를 기다리고 있어요(마지막 연결 ${mdhm(T)}). PC가 연결되면 이어서 정리해요.`;
  expect(await go("offline", "queued")).toEqual(["wait", off]);
  expect(await go("offline", "running")).toEqual(["wait", off]);
  expect(await go("recent", "queued")).toEqual(["wait", "정리하고 있어요…"]);
});

test("장치 없음 + 확정 전 세션 — 작업 접수 0(새 턴·재정리·막힘 답) · 안내 1줄 · 끄기·확정은 된다 · 확정 뒤 상태 다시 받기", async () => {
  const reload = vi.fn(async () => {});
  const s = mk();
  s.api.exclude = vi.fn(async (_p: string, cids: string[]) => ({ ok: true as const, j: { preview: pv({ id: "p2", preview_version: 2, preview_sha: "h2", changes: [pv().changes[0]], excluded: cids }) } }));
  s.sync(st({ stack_session: { id: "s1", expires_at: T }, devices_status: { state: "none", last_seen_at: null, threshold_seconds: 180 } }), reload);
  expect([s.open, s.sid]).toEqual([true, "s1"]);
  expect(s.api.session).toHaveBeenCalledTimes(1);   // 확정은 서버 작업 — 장치 없어도 이어 받는다
  s.want = "j1"; s.show(pv(), "j1", "r1");
  s.input = "새 말"; await s.send(); await s.restack(); await s.restack({ answers: [{ cid: null, text: "답" }] });
  expect([(s.api.send as ReturnType<typeof vi.fn>).mock.calls.length, s.line, s.dirty, s.canSend()]).toEqual([0, NODEV, false, false]);
  await s.exclude("c2");
  expect(s.preview!.id).toBe("p2");
  await s.confirm();
  expect((s.api.confirm as ReturnType<typeof vi.fn>).mock.calls[0][1].preview_id).toBe("p2");
  expect([s.line, s.sid]).toEqual(["저장했어요. 변경 1건", ""]);
  expect(reload).toHaveBeenCalledTimes(1);
});

test("오프라인에 보내기 — 막지 않는다 · 첫 롱폴 전에도 진행 중이 아니라 PC 대기 문구 · 롱폴이 queued 를 줘도 같은 문구 · 최근 연결 = 정리하고 있어요", async () => {
  const go = async (state: string) => {
    const s = mk(); s.S = st({ devices_status: { state, last_seen_at: T, threshold_seconds: 180 } }); s.input = "오늘 회의 메모";
    expect(s.canSend()).toBe(true);
    await s.send();
    return [(s.api.send as ReturnType<typeof vi.fn>).mock.calls.length, s.line, s.turns.length];
  };
  const wait = `PC를 기다리고 있어요(마지막 연결 ${mdhm(T)}). PC가 연결되면 이어서 정리해요.`;
  expect(await go("offline")).toEqual([1, wait, 1]);
  expect(await go("recent")).toEqual([1, "정리하고 있어요…", 1]);
  const s = mk(); s.S = st({ devices_status: { state: "offline", last_seen_at: null, threshold_seconds: 180 } }); s.input = "메모";
  let n = 0;
  s.api.poll = vi.fn(async () => (++n === 1 ? { ok: true as const, j: { id: "jx", status: "queued" } } : new Promise(() => {}))) as unknown as typeof s.api.poll;
  await s.send(); await new Promise(r => setTimeout(r, 1100));
  expect([n, s.line]).toEqual([2, "PC를 기다리고 있어요. PC가 연결되면 이어서 정리해요."]);
});
