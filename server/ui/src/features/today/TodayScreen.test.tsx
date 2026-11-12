// 「오늘」·저장 승인 대기(옛 test_web_home.py S5 절·test_web_import.py 승인 대기 정적 절 + 화면 동작을 옮김, R4-2) —
// 줄 = 대기 + 승인해 저장된 내 글(ingest_kind=inbox) + 활동 · 들어온 날(KST) 머리글 · 활동 5줄 + 「더 N」 · [삭제] 0 ·
// 대기 하나 = 서버 승인 문구 그대로 · 생성 정보 = 사람 말(모르는 값 = 「기타」 + 원값) · 승인·제외(확인창) → 오늘 · 지난 승인 대기 목록(상태 알약·더 보기)
import { act } from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { queryClient } from "../../shared/queries";
import { calls, click, flush, installFetch, json, serve, text } from "../../test/fakeServer";
import { installMedia } from "../../test/meFixture";
import { byText, hideScreen, reload, showScreen } from "../../test/showScreen";
import sample from "./today.sample.json";
import { SELF_NOTE } from "./text";

const now = new Date().toISOString();
const ent = (id: string, kind: string, extra: object = {}) => ({ ...sample.list.entries[0], id, kind, received_at: now, title: `${id} 제목`, generation: null, ...extra });
const PEND = { entries: [ent("e1", "self_text"), ent("e2", "self_summary")], next_cursor: "", counts: { pending: 2 } };
const ACTS = { activities: Array.from({ length: 6 }, (_, i) => ({ id: `a${i}`, action: "like", occurred_on: null, received_at: now, source: { id: "s", name: `출처${i}` }, people: [] })), next_cursor: "" };
const S = { user: { nav: "new" }, switches: { trash: true }, activity_ui: { actions: { like: "좋아요" }, providers: {}, pending_days: 30 }, inbox: { pending: 2 },
  journal: [{ id: "r9", title: "승인한 글", excerpt: "", created: now, source_date: null, ingest_kind: "inbox" }, { id: "r8", title: "그냥 글", created: now, ingest_kind: null }] };
const confirm = vi.fn((_ask?: string) => true);
let ONE: object = sample.one, POST: (url: string) => Response = () => json(200, {});
const show = (hash: string, args: string[]) => showScreen("today", hash, args, S);
const posts = () => calls.filter(c => c.method === "POST").map(c => c.url);

beforeEach(() => {
  installFetch(); installMedia(false); queryClient.clear(); reload.mockClear(); confirm.mockReturnValue(true);
  vi.stubGlobal("confirm", confirm);
  ONE = sample.one; POST = () => json(200, {});
  serve((url, m) => {
    if (m === "POST") return POST(url);
    if (url === "/api/inbox?state=pending") return json(200, PEND);
    if (url.startsWith("/api/inbox?state=all")) return json(200, url.includes("cursor=") ? { entries: [ent("e5", "self_text", { state: "expired" })], next_cursor: "", counts: { pending: 2 } }
      : { entries: [ent("e3", "self_text", { state: "applied", title: null, target_record_id: "r9" }), ent("e4", "self_text", { state: "excluded", title: null })], next_cursor: "c2", counts: { pending: 2 } });
    if (url === "/api/activities?limit=50") return json(200, ACTS);
    if (url.startsWith("/api/inbox/")) return json(200, ONE);
    return json(404, {});
  });
});
afterEach(() => { hideScreen(); vi.unstubAllGlobals(); });

test("오늘 목록 — 대기·보관됨 줄 · 오늘 머리글(KST) · 그냥 쓴 글 0 · 활동 5줄 + 「더 1」 · [삭제]·쓰기 0", async () => {
  const el = await show("#_today", ["today", "", ""]);
  expect(calls.map(c => c.url).sort()).toEqual(["/api/activities?limit=50", "/api/inbox?state=pending"]);
  expect(el.querySelector("h3:not(#today-h)")!.textContent).toMatch(/^오늘, /);
  expect(el.textContent).toContain("대기 2");
  const kinds = text(el, ".hrows .ht").map(t => t!.replace(/\s+/g, " ").trim());
  expect(kinds.filter(k => k.startsWith("대기"))).toEqual(["대기 내 글 e1 제목", "대기 내 글 AI 요약 e2 제목"]);
  expect(kinds).toContain("보관됨 내 글 승인한 글");
  expect(kinds.some(k => k.includes("그냥 글"))).toBe(false);
  expect(kinds.filter(k => k.includes("좋아요"))).toHaveLength(5);
  await click(byText(el, "button", "더 1")[0]);
  expect(text(el, ".hrows .ht").filter(k => k!.includes("좋아요"))).toHaveLength(6);
  expect(el.querySelector('a[href="#_today/inbox/e1"]')).not.toBeNull();
  expect(el.querySelector('a[href="#_me/journal/r9"]')).not.toBeNull();
  expect(byText(el, "button", "삭제")).toEqual([]);
  expect(posts()).toEqual([]);
  expect(el.textContent).toContain("대기 글을 고르면 여기서 승인하거나 제외해요.");
});

test("대기 하나 — 서버 승인 문구 그대로 · 생성 정보 사람 말·코드·기타 · 승인 = POST → 오늘 + 결과 한 줄 · 제외 = 확인창 → POST", async () => {
  ONE = { ...sample.one, generation: { ...sample.one.generation, method: "weird" } };
  const el = await show("#_today/inbox/ie_s1", ["today", "inbox", "ie_s1"]);
  expect(el.querySelector('.hrows a[aria-current="true"]')).toBeNull();   // 고른 줄 = 목록에 그 id 가 있을 때만(이 견본 id 는 목록 밖)
  expect(el.textContent).toContain(sample.one.approve_notice!);
  const kv = [...el.querySelectorAll("dl.kv")][1];
  expect(kv.textContent).toContain("기타 weird");
  expect(kv.textContent).toContain("내 글만");
  expect(kv.querySelector("code")!.textContent).toBe("demo-tool");
  expect(kv.textContent).toContain("3편");
  await click(byText(el, "button", "승인")[0]);
  expect(posts()).toEqual(["/api/inbox/ie_s1/approve"]);
  expect(location.hash).toBe("#_today");
  expect(el.querySelector(".hhead .fok")!.textContent).toBe("승인했어요. 내 글로 저장했어요.");
  expect(reload).toHaveBeenCalledTimes(1);
  confirm.mockReturnValueOnce(false);
  const e2 = await show("#_today/inbox/ie_s1", ["today", "inbox", "ie_s1"]);
  await click(byText(e2, "button", "제외")[0]);
  expect(posts()).toHaveLength(1);
  await click(byText(e2, "button", "제외")[0]);
  expect(confirm).toHaveBeenLastCalledWith("이 글을 제외할까요? 대기 본문이 지워지고 되돌릴 수 없어요.");
  expect(posts().at(-1)).toBe("/api/inbox/ie_s1/exclude");
});

test("대기 하나 — 내 글 안내(서버 문구 없음) · 승인 못 함(더 새 개정) = 버튼 끔 + 이유 · 충돌 = 머리 문구 + 다시 받기 · 그 밖 = 자리에 서버 문구", async () => {
  ONE = { ...sample.one, kind: "self_text", generation: null, approve_notice: null, approvable: false, is_latest: false };
  const el = await show("#_today/inbox/x", ["today", "inbox", "x"]);
  expect(el.textContent).toContain(SELF_NOTE);
  expect((byText(el, "button", "승인")[0] as HTMLButtonElement).disabled).toBe(true);
  expect(el.textContent).toContain("더 새 개정이 들어와서 이 개정은 승인할 수 없어요.");
  ONE = sample.one;
  queryClient.clear();
  POST = () => json(400, { code: "CONFLICT", msg: "" });
  const e2 = await show("#_today/inbox/y", ["today", "inbox", "y"]);
  await click(byText(e2, "button", "승인")[0]);
  expect(e2.querySelector(".hhead .fok")!.textContent).toBe("다른 곳에서 먼저 바뀌었어요. 다시 불러왔어요. 확인하고 다시 해 주세요.");
  expect(reload).toHaveBeenCalledTimes(1);
  POST = () => json(503, { code: "APPROVALS-OFF", msg: "승인 대기 글의 승인은 지금 꺼져 있어요." });
  await click(byText(e2, "button", "승인")[0]);
  expect(e2.querySelector("#home-detail .ferr")!.textContent).toBe("승인 대기 글의 승인은 지금 꺼져 있어요.");
});

test("1열 — 목록만 · 대기 하나 = 상세만 + 「목록」(목록에서 왔으면 뒤로) · 옛 주소 #_today/<그 밖> = #_today 로", async () => {
  installMedia(true);
  const el = await show("#_today", ["today", "", ""]);
  expect(el.querySelector("#home-list")).not.toBeNull();
  expect(el.textContent).not.toContain("대기 글을 고르면");
  const d = await show("#_today/inbox/ie_s1", ["today", "inbox", "ie_s1"]);
  expect(d.querySelector("#home-list")).toBeNull();
  await click(byText(d, "button", "목록")[0]);
  expect(location.hash).toBe("#_today");
  await show("#_today/zzz", ["today", "zzz", ""]);
  expect(location.hash).toBe("#_today");
});

test("지난 승인 대기 — 위치(오늘 › 저장 승인 대기) · 상태 알약(대기 수) · 줄 = 처리 상태·저장된 글 제목 · [더 보기] = 커서", async () => {
  const el = await show("#_inbox/all", ["inbox", "all"]);
  expect(el.querySelector('.crumbs a[href="#_today"]')).not.toBeNull();
  expect(text(el, "nav.pills a")).toEqual(["대기2", "승인함", "제외함", "만료", "전체"]);
  expect(el.querySelector('nav.pills a[aria-current="true"]')!.textContent).toBe("전체");
  expect(text(el, "li.inrow b")).toEqual(["승인한 글", "(대기 본문을 지웠어요)"]);
  expect(text(el, "li.inrow .meta")[0]).toContain("승인함");
  expect(el.textContent).toContain("대기 본문은 30일 보관하고");
  await click(byText(el, "button", "더 보기")[0]);
  expect(calls.at(-1)!.url).toBe("/api/inbox?state=all&cursor=c2");
  expect(text(el, "li.inrow b")).toHaveLength(3);
});

test("저장 승인 대기 백그라운드 재조회 실패 = 기존 목록 유지 + 오류 안내", async () => {
  const el = await show("#_inbox/all", ["inbox", "all"]);
  expect(text(el, "li.inrow b")).toHaveLength(2);
  serve((url) => url.startsWith("/api/inbox?") ? json(503, { code: "OFFLINE", msg: "" }) : json(404, {}));
  await act(async () => { await queryClient.invalidateQueries({ queryKey: ["inbox", "list"] }); });
  await flush();
  expect(text(el, "li.inrow b")).toHaveLength(2);
  expect(el.querySelector('[role="alert"]')?.textContent).toContain("저장 승인 대기를 불러오지 못했어요");
});
