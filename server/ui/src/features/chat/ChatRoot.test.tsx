// 대화 서랍 화면 — 옛 test_web_home.py test_static_chat·test_chat_devices·test_chat_nodev_session·test_chat_excluded 의 화면 단언을 옮김(R3).
// 껍데기 고정 자리(#ui-chatnav · #ui-chatnote)를 만들고 ChatRoot 를 띄운다. 서버 접점은 가짜(test/chat mk).
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { mdhm } from "../../shared/date";
import type { AppState } from "../../shared/state";
import { ch, mk, NODEV, pv, st, T } from "../../test/chat";
import { flush } from "../../test/fakeServer";
import { ChatRoot } from "./ChatRoot";
import type { ChatStore } from "./store";

let el: HTMLDivElement, nav: HTMLSpanElement, noteM: HTMLDivElement, root: Root;
const reload = vi.fn(async () => {});
beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  nav = document.createElement("span"); nav.id = "ui-chatnav";
  noteM = document.createElement("div"); noteM.id = "ui-chatnote";
  el = document.createElement("div");
  document.body.append(nav, noteM, el); root = createRoot(el); reload.mockClear();
});
afterEach(() => { act(() => root.unmount()); el.remove(); nav.remove(); noteM.remove(); });
async function show(s: ChatStore, S: AppState) { await act(async () => root.render(<ChatRoot ctx={{ reload, state: S }} store={s} />)); await flush(); }
const aside = () => el.querySelector("aside#chat") as HTMLElement | null;
const q = <E extends Element>(sel: string) => el.querySelector(sel) as E;
const btn = (t: string) => [...el.querySelectorAll("button")].find(b => b.textContent === t) as HTMLButtonElement;
// 남의 장치 정보가 devices_status 에 섞여 와도 화면에 나오지 않는다(화면은 state·last_seen_at 만 읽는다)
const leak = { devices: [{ id: "dv-other", label: "남의장치라벨" }], user: { email: "other@example.com" }, label: "남의장치라벨", user_id: "u-other" };
const OFFLINE = "PC나 연결 장치가 꺼져 있어 지금은 정리되지 않아요. MyCRM 앱 메뉴의 연결 장치(⌘2, Windows는 Ctrl+2)에서 [연결 장치 시작]을 누르면 보낸 글을 이어서 정리해요(첫 입력 뒤 24시간까지).";
const dev = (state: string, last: string | null = T, x: object = {}) => ({ devices_status: { state, last_seen_at: last, threshold_seconds: 180, ...x } });

test("장치 상태 — 없음 = 버튼 대신 안내(탭 줄·좁은 화면 한 줄) · 최근 연결 · 오프라인 = 마지막 연결 · 필드 없음·모르는 값 = 현행 · 스위치 꺼짐 = 버튼·서랍 0 · 남 장치 0", async () => {
  const look = async (S: AppState) => {
    const s = mk(); s.open = true; await show(s, S);   // 옛 시험 look() — 열려 있던 서랍에 새 상태
    return { nav: nav.childElementCount, hasA: !!nav.querySelector("a"), navText: nav.textContent, note: noteM.textContent, open: s.open, hidden: aside()?.hidden ?? true,
      ctx: aside()?.querySelector("header span")?.textContent ?? "", dnote: (aside()?.querySelector("p[role=note]") as HTMLElement | null)?.hidden === false ? aside()!.querySelector("p[role=note]")!.textContent : "", form: (aside()?.querySelector("form") as HTMLElement | null)?.hidden ?? true, sid: s.sid, q: s.queuedLine() };
  };
  const sess = { stack_session: { id: "s-old", expires_at: T } };
  const n = await look(st(dev("none", null, leak)));
  expect([n.navText, n.hasA, n.note, n.sid, n.form, n.dnote]).toEqual([NODEV, false, NODEV, "", true, NODEV]);
  const r = await look(st({ ...sess, ...dev("recent", T, leak) }));
  expect([r.navText, r.ctx, r.open, r.hidden, r.note, r.dnote]).toEqual(["대화", "최근 연결, 임시 보관", true, false, "", ""]);
  expect(r.q).toBe("PC 가 받기를 기다리고 있어요… PC 가 켜져 있어야 정리돼요.");
  const f = await look(st({ ...sess, ...dev("offline", T, leak) }));
  expect([f.navText, f.ctx, f.form, f.dnote]).toEqual(["대화", `PC 오프라인, 마지막 연결 ${mdhm(T)}, 임시 보관`, false, OFFLINE]);   // 오프라인 = 입력 칸 그대로 + 할 일 안내
  expect(f.q).toBe(`PC를 기다리고 있어요(마지막 연결 ${mdhm(T)}). PC가 연결되면 이어서 정리해요.`);
  const f0 = await look(st({ ...sess, ...dev("offline", null) }));
  expect([f0.ctx, f0.q.includes("마지막 연결")]).toEqual(["PC 오프라인, 임시 보관", false]);
  for (const x of [await look(st(sess)), await look(st({ ...sess, ...dev("busy") }))])
    expect([x.navText, x.ctx, x.open, x.q, x.dnote]).toEqual(["대화", "임시 보관", true, "PC 가 받기를 기다리고 있어요… PC 가 켜져 있어야 정리돼요.", ""]);
  for (const d of [dev("none"), dev("recent"), dev("offline"), {}]) {
    const o = await look(st({ ...sess, ...d, switches: { trash: false, converse: false } }));
    expect([o.nav, o.note, o.open, o.hidden]).toEqual([0, "", false, true]);
  }
  expect(document.body.textContent).not.toMatch(/남의장치라벨|dv-other|other@example\.com|u-other|실행 가능/);
});

test("서랍 — 버튼 3(닫기·보내기·확정) · 바뀌는 것 기본 포함 · [정리 반영] 0 · 버튼으로 열면 입력 칸 초점 · Esc 닫기 · 새 상태 두 번 뒤에도 버튼 살아 있음", async () => {
  const s = mk(); const S = st(dev("recent"));
  await show(s, S); await show(s, { ...S }); await show(s, { ...S });
  const a = nav.querySelector("a")!;
  expect([a.textContent, a.getAttribute("aria-pressed"), aside()!.hidden]).toEqual(["대화", "false", true]);
  await act(async () => a.click()); await flush();
  expect([aside()!.hidden, document.body.classList.contains("chat-open"), document.activeElement?.getAttribute("aria-label")]).toEqual([false, true, "대화 입력"]);
  await act(async () => { s.want = "j1"; s.show(pv(), "j1", "r1"); });
  expect([...aside()!.querySelectorAll("button")].map(b => b.textContent)).toEqual(["닫기", "확정", "보내기"]);
  expect([...el.querySelectorAll<HTMLInputElement>("input[data-cid]")].map(x => [x.dataset.cid, x.checked, x.disabled])).toEqual([["c1", true, false], ["c2", true, false]]);
  expect(el.textContent).not.toContain("정리 반영");
  expect(q("p[role=status]").textContent).toBe("확인하고 [확정]을 눌러 주세요.");
  await act(async () => { aside()!.querySelector("textarea")!.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true })); });
  expect([s.open, document.body.classList.contains("chat-open")]).toEqual([false, false]);
});

test("정리 글 고침 = 즉시 [확정] 잠금(요청 0) · 정리 글 안에서 칸 옮김 = 그대로 · 밖으로 = 재정리 1 · 입력 칸·카운터·원문으로 저장", async () => {
  const s = mk(); await show(s, st(dev("recent"))); s.toggle(true); s.sid = "s1";
  await act(async () => { s.want = "j1"; s.show(pv(), "j1", "r1"); });
  const [t1, t2] = [...el.querySelectorAll<HTMLTextAreaElement>("textarea[data-uid]")];
  const type = (x: HTMLTextAreaElement | HTMLInputElement, v: string) => act(async () => {
    Object.getOwnPropertyDescriptor(Object.getPrototypeOf(x), "value")!.set!.call(x, v); x.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await type(t1, "하나 고침");
  expect([btn("확정").disabled, s.line, (s.api.send as ReturnType<typeof vi.fn>).mock.calls.length]).toEqual([true, "고친 글은 입력 칸을 벗어나면 다시 정리해요.", 0]);
  expect([...el.querySelectorAll<HTMLInputElement>("input[data-cid]")].every(x => x.disabled)).toBe(true);
  await act(async () => { t1.focus(); t2.focus(); });
  expect((s.api.send as ReturnType<typeof vi.fn>).mock.calls.length).toBe(0);
  await act(async () => { t2.blur(); }); await flush();
  expect((s.api.send as ReturnType<typeof vi.fn>).mock.calls[0][0].restack).toEqual({ parent_result_version: "r1", edit_generation: 1, edited_text: "하나 고침\n\n둘" });
  const inp = aside()!.querySelector<HTMLTextAreaElement>("form textarea")!;
  expect([q<HTMLLabelElement>("form label").hidden, q("form span").textContent]).toEqual([true, "0 / 8,000"]);   // 세션이 있으면 원문으로 저장 숨김
  await type(inp, "가".repeat(8001));
  expect([q("form span").className.includes("bad"), btn("보내기").disabled]).toEqual([true, true]);
});

test("뺀 것 = 미리보기 excluded 그대로(연쇄 포함) · 이름 = 빼기 전 본 변경 → 서버 excluded_changes → 「앞서 뺀 변경」 · 체크 칸 0 · 확정 = 그 미리보기 · 저장 수 = 포함만", async () => {
  const s = mk(); await show(s, st(dev("recent"))); s.toggle(true);
  const p1 = pv({ units: [{ uid: "u1", text: "하나", change_ids: ["c1"] }, { uid: "u2", text: "둘", change_ids: ["c2", "c3"] }],
    changes: [ch("c1", "새 결정: 가"), ch("c2", "새 판단: 나"), ch("c3", "새 판단: 다", { depends_on: ["c2"] })] });
  const p2 = { ...p1, id: "p2", preview_version: 2, preview_sha: "h2", units: [p1.units[0]], changes: [p1.changes[0]], excluded: ["c2", "c3"] };
  const outs = () => [...el.querySelectorAll("li[data-xcid]")].map(li => [li.getAttribute("data-xcid"), li.firstElementChild!.textContent, li.querySelector("input")]);
  await act(async () => { s.want = "j1"; s.show(p1, "j1", "r1"); });
  expect([outs(), el.textContent!.includes("뺀 것"), el.textContent!.includes("바뀌는 것 3")]).toEqual([[], false, true]);
  s.api.exclude = vi.fn(async () => ({ ok: true as const, j: { preview: p2, removed: ["c2", "c3"] } }));
  await act(async () => { el.querySelectorAll<HTMLInputElement>("input[data-cid]")[1].click(); }); await flush();
  expect(s.api.exclude).toHaveBeenCalledWith("p1", ["c2"]);
  expect(outs()).toEqual([["c2", "새 판단: 나", null], ["c3", "새 판단: 다", null]]);
  expect([el.textContent!.includes("뺀 것 2"), el.textContent!.includes("바뀌는 것 1"), el.querySelectorAll("#chat-card button").length]).toEqual([true, true, 1]);
  await act(async () => btn("확정").click()); await flush();
  expect((s.api.confirm as ReturnType<typeof vi.fn>).mock.calls[0][1]).toMatchObject({ preview_id: "p2", preview_version: 2, preview_sha: "h2" });
  expect([s.line, reload.mock.calls.length]).toEqual(["저장했어요. 변경 1건", 1]);
  await act(async () => { s.reset(); s.want = "j2"; s.show({ ...p2 }, "j2", "r1"); });
  expect(outs().map(o => o[1])).toEqual(["앞서 뺀 변경", "앞서 뺀 변경"]);   // 새로 고침 뒤(본 변경 없음) = 이름 없이 같은 수
  await act(async () => { s.reset(); s.want = "j5"; s.show({ ...p2, excluded_changes: [{ cid: "c2", summary: "새 판단: 나" }, { cid: "c3", summary: "새 판단: 다" }] }, "j5", "r1"); });
  expect(outs().map(o => o[1])).toEqual(["새 판단: 나", "새 판단: 다"]);
  await act(async () => { s.reset(); s.want = "j1"; s.show(p1, "j1", "r1"); s.want = "j3"; s.show({ ...p2, id: "p3" }, "j3", "r2"); });
  expect(outs().map(o => o[1])).toEqual(["앞서 뺀 변경", "앞서 뺀 변경"]);   // 다른 결과의 같은 ID 에 옛 이름 0
});

test("장치 없음 + 확정 전 세션 화면 — 입력 칸 대신 안내 1줄 · 정리 글 읽기만 · 막힘 답 잠금 · 확정 뒤 세션 없으면 탭 줄은 다시 안내", async () => {
  const s = mk(); const S = st({ stack_session: { id: "s1", expires_at: T }, ...dev("none", null) });
  await show(s, S);
  expect([s.open, nav.textContent, aside()!.hidden]).toEqual([true, "대화", false]);   // 세션이 있는 동안 = 다시 여는 「대화」
  await act(async () => { s.want = "j1"; s.show(pv({ blocked: [{ cid: null, code: "x", question: "누구?" }] }), "j1", "r1"); });
  expect([q<HTMLFormElement>("form").hidden, q("p[role=note]").textContent]).toEqual([true, NODEV]);
  expect([q<HTMLTextAreaElement>("textarea[data-uid]").readOnly, q<HTMLInputElement>("input[data-bq]").disabled]).toEqual([true, true]);
  await act(async () => { s.reset(); s.line = "저장했어요. 변경 1건"; s.draw(); });
  await show(s, { ...S, stack_session: null });
  expect([nav.textContent, noteM.textContent]).toEqual([NODEV, NODEV]);
});
