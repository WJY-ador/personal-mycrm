// 「자료 종류」(옛 test_web_home.py 휴지통 진입점·test_static_moved 절 + 화면 동작을 옮김, R4-2) — 색인 카드 · 사람(별칭만 · 클릭 편집 · [삭제] 켜짐 = 휴지통,
// 꺼짐 = 즉시 삭제 + 확인창 문구 그대로) · 출처(저장 → 그 출처) · 읽고 든 생각(확인 · 쓰기 · 고치기 · 삭제) · 실패 = 서버 문구(충돌 = 머리 + 다시 받기)
import { act } from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { queryClient } from "../../shared/queries";
import { calls, click, flush, installFetch, json, serve } from "../../test/fakeServer";
import { type } from "../../test/showMe";
import { byText, hideScreen, reload, showScreen } from "../../test/showScreen";
import sample from "./objects.sample.json";
import { TRASH_ASK } from "./text";

const T = "2026-11-03T13:51:59+09:00";
const st = (trash = true, nav = "new") => ({
  user: { nav, display_name: "홍길동" }, switches: { trash }, activity_ui: { actions: { like: "좋아요" }, providers: {}, pending_days: 30 },
  people: [{ id: "p1", alias: "홍길동 동료", revision: 2, created: T, updated: T }],
  sources: [{ id: "s1", kind: "file", name: "회고 노트", location: "notes/retro.md" }, { id: "s2", kind: "url", name: "읽은 글", location: "" }],
  reflections: [{ id: "x1", source_id: "s1", kind: "summary", body: "회고는 **금요일**에.", review: "reviewed", revision: 3, created: T, updated: T, reviewed_at: T },
    { id: "x2", source_id: "s1", kind: "reaction", body: "흐름이 보인다.", review: "pending", revision: 0, created: T, updated: T, reviewed_at: null }],
  journal: [{ id: "r1", title: "홍길동 메모", excerpt: "", created: T, source_id: "s1", ingest_kind: null }], source_counts: { by_source: { s1: 1 }, unconfirmed: 2 },
  questions: [{ id: "q1" }], candidates: [{ id: "c1", status: "pending" }], items: [{ id: "i1", object_id: "od_x" }], definitions: [{ id: "od_principles", label: "기준", fields: [{ key: "people", label: "사람" }] }],
  structure: { objects: [{ id: "od_ax", key: "axes", label: "축", origin: "standard" }, { id: "od_x", key: "homework", label: "숙제", origin: "template" }] },
  origin_labels: { text: { core: "표준", standard: "표준", template: "커스텀", custom: "커스텀" }, category: { core: "standard", standard: "standard", template: "template", custom: "template" } },
  me: { counts: { people: 1, sources: 2, reflections: 2 } }, activity: { total: 5 }, tabs: [],
});
const confirm = vi.fn((_ask?: string) => true);
let POST: (url: string) => Response = () => json(200, {});
const show = (hash: string, args: string[], s: object = st()) => showScreen("objects", hash, args, s);
const posts = () => calls.filter(c => c.method === "POST").map(c => ({ url: c.url, body: c.body }));
const submit = (el: Element, label: string) => click(byText(el, "button", label)[0]);

beforeEach(() => {
  installFetch(); queryClient.clear(); reload.mockClear(); confirm.mockClear(); confirm.mockReturnValue(true);
  vi.stubGlobal("confirm", confirm);
  POST = () => json(200, {});
  serve((url, m) => {
    if (m === "POST") return POST(url);
    if (url.startsWith("/api/people/")) return json(200, { ...sample.person, old_revision_links: 2 });
    if (url.startsWith("/api/sources/")) return json(200, sample.source);
    return json(404, {});
  });
});
afterEach(() => { hideScreen(); vi.unstubAllGlobals(); });

test("색인 — 표준 자물쇠(코어 + 표준 정의)·커스텀(칩 = 커스텀) · 개수 = 상태 그대로 · 카드 = 그 화면 주소 · 문의 카드는 대화창이 있을 때만", async () => {
  const el = await show("#_setup/objects", ["", "", ""]);
  expect([...el.querySelectorAll("section > h3")].map(h => h.firstChild!.textContent)).toEqual(["표준 ", "커스텀"]);
  expect(el.querySelector("section > h3 svg")!.getAttribute("aria-label")).toBe("표준 정의 보호");
  const cards = [...el.querySelectorAll(".asset-card")].map(c => [c.querySelector("h3")!.textContent, c.querySelector(".meta")!.textContent]);
  expect(cards).toContainEqual(["내 글", "3"]);
  expect(cards).toContainEqual(["활동", "최근 30일 5"]);
  expect(cards).toContainEqual(["축", "항목 0"]);
  expect(cards.map(c => c[0])).not.toContain("문의");
  expect(el.querySelector(".asset-card .chip.o-tpl")!.textContent).toBe("커스텀");
  expect(el.textContent).not.toMatch(/records|candidates|source_reflections|activities|questions/);   // 영문 DB 이름은 화면에 안 나온다
  await click(byText(el, ".asset-card h3", "사람")[0].closest("article"));
  expect(location.hash).toBe("#_obj/person");
  expect(calls).toEqual([]);   // 읽기 = 상태뿐
});

test("사람 추가 — 별칭 한 칸뿐(연락처·평가 칸 0) · 빈 값 = 요청 0 · 저장 = POST /api/people {alias} → 결과 한 줄 + 다시 받기", async () => {
  const el = await show("#_obj/person", ["person", "", ""]);
  expect([...el.querySelectorAll("form input, form textarea, form select")].map(x => (x as HTMLInputElement).name)).toEqual(["alias"]);
  await submit(el, "추가");
  expect(el.querySelector(".ferr")!.textContent).toBe("별칭을 적어 주세요.");
  expect(posts()).toEqual([]);
  await type(el.querySelector("#person-new-alias")!, "새 사람(가명)");
  await submit(el, "추가");
  expect(posts()).toEqual([{ url: "/api/people", body: { alias: "새 사람(가명)" } }]);
  expect(el.querySelector("#core-msg")!.textContent).toBe("사람을 추가했어요.");
  expect(reload).toHaveBeenCalledTimes(1);
});

test("사람 하나 — 별칭 = 상시 연필 클릭 편집(저장 = revision 같이) · 문맥 링크 = 주소만 · 휴지통 켜짐 [삭제] = r4 확인창 → 휴지통 → 목록", async () => {
  const el = await show("#_obj/person/p1", ["person", "p1", ""]);
  expect(el.querySelector('h2.title button svg[aria-label="고치기"]')).not.toBeNull();
  expect(el.textContent).not.toContain("옛 판 활동 연결");   // 켜짐 = 휴지통이 옛 판 연결도 옮긴다
  expect(el.querySelector('a[href="#_me/journal/r_sample"]')).not.toBeNull();
  expect(el.querySelector('a[href="#structure/od_principles/i_sample"]')!.parentElement!.textContent).toContain("기준, 사람");
  await click(el.querySelector("h2.title button"));
  await type(el.querySelector("#hedit-input")!, "고친 별칭");
  await submit(el, "저장");
  expect(posts()).toEqual([{ url: "/api/people/p1", body: { alias: "고친 별칭", expected_revision: 2 } }]);
  expect(el.textContent).toContain("별칭을 고쳤어요.");
  await submit(el, "삭제");
  expect(confirm).toHaveBeenLastCalledWith(TRASH_ASK);
  expect(posts().at(-1)).toEqual({ url: "/api/trash/move", body: { kind: "person", id: "p1", expected_revision: 2 } });
  expect(location.hash).toBe("#_obj/person");
});

test("휴지통 꺼짐 — 사람·읽고 든 생각 [삭제] = 기존 즉시 삭제(확인창 문구 그대로) · 옛 판 연결 안내 · 취소 = 요청 0", async () => {
  const el = await show("#_obj/person/p1", ["person", "p1", ""], st(false));
  expect(el.textContent).toContain("옛 판 활동 연결이 2개 있어 지울 수 없어요.");
  confirm.mockReturnValueOnce(false);
  await submit(el, "삭제");
  expect(posts()).toEqual([]);
  await submit(el, "삭제");
  expect(confirm).toHaveBeenLastCalledWith("이 사람을 지울까요? 되돌릴 수 없어요.");
  expect(posts()).toEqual([{ url: "/api/people/p1/delete", body: { expected_revision: 2 } }]);
  const r = await show("#_obj/reflection/x1", ["reflection", "x1", ""], st(false));
  await submit(r, "삭제");
  expect(confirm).toHaveBeenLastCalledWith("이 읽고 든 생각을 지울까요? 되돌릴 수 없어요.");
  expect(posts().at(-1)).toEqual({ url: "/api/reflections/x1/delete", body: { expected_revision: 3 } });
  expect(location.hash).toBe("#_obj/source/s1");
});

test("출처 — 종류·이름·위치 저장 = POST /api/sources → 그 출처 주소 · 출처 하나 = 내 글·요약·반응·활동 + 쓰기 폼(출처 미리 고름)", async () => {
  POST = () => json(200, { id: "s9" });
  const el = await show("#_obj/source", ["source", "", ""]);
  await click(el.querySelector('input[name="kind"][value="url"]'));
  await type(el.querySelector("#source-new-name")!, "새 출처");
  await submit(el, "출처 저장");
  expect(posts()).toEqual([{ url: "/api/sources", body: { kind: "url", name: "새 출처", location: "" } }]);
  expect(location.hash).toBe("#_obj/source/s9");
  const one = await show("#_obj/source/s1", ["source", "s1", ""]);
  expect(one.querySelector('a[href="#_me/journal/r1"]')!.textContent).toBe("홍길동 메모");
  expect([...one.querySelectorAll("h2.sh")].map(h => h.firstChild!.textContent!.trim())).toEqual(["내 글", "내 요약", "내 반응", "읽고 든 생각 쓰기"]);
  expect(one.querySelector(".bars")).not.toBeNull();
  expect((one.querySelector("#refl-new-src") as HTMLSelectElement).value).toBe("s1");
});

test("읽고 든 생각 — 확인(판단 확정 아님 문구) · 쓰기(유형 필수) · 고치기 = 서버 review 로 문구 · 충돌 = 머리 문구 + 다시 받기", async () => {
  const el = await show("#_obj/reflection", ["reflection", "", ""]);
  await submit(el, "확인했어요");
  expect(posts()).toEqual([{ url: "/api/reflections/x2/review", body: { reviewed: true, expected_revision: 0 } }]);
  expect(el.querySelector("#core-msg")!.textContent).toBe("확인했어요로 표시했어요. 판단 확정은 아니에요.");
  const n = await show("#_obj/reflection/new/s2", ["reflection", "new", "s2"]);
  expect((n.querySelector("#refl-new-src") as HTMLSelectElement).value).toBe("s2");
  await type(n.querySelector("#refl-new-body")!, "내 생각");
  await submit(n, "저장");
  expect(n.querySelector(".ferr")!.textContent).toBe("내 요약과 내 반응 중 하나를 골라 주세요.");
  await click(n.querySelector('input[name="kind"][value="reaction"]'));
  await submit(n, "저장");
  expect(posts().at(-1)).toEqual({ url: "/api/reflections", body: { source_id: "s2", kind: "reaction", body: "내 생각" } });
  expect(location.hash).toBe("#_obj/source/s2");
  POST = () => json(200, { review: "pending" });
  const d = await show("#_obj/reflection/x1", ["reflection", "x1", ""]);
  expect(d.textContent).toContain("고치면 확인 전으로 돌아가요.");
  await type(d.querySelector("#refl-edit-body")!, "고친 생각");
  await submit(d, "고친 내용 저장");
  expect(posts().at(-1)).toEqual({ url: "/api/reflections/x1", body: { source_id: "s1", kind: "summary", body: "고친 생각", expected_revision: 3 } });
  expect(d.querySelector("#core-msg")!.textContent).toBe("고쳤어요. 확인 전으로 돌아갔어요.");
  POST = () => json(400, { code: "CONFLICT", msg: "revision 이 달라요" });
  reload.mockClear();
  await submit(d, "확인 전으로");
  expect(d.querySelector("#core-msg")!.textContent).toBe("다른 곳에서 먼저 바뀌었어요. 다시 불러왔어요. 확인하고 다시 해 주세요.");
  expect(reload).toHaveBeenCalledTimes(1);
  POST = () => json(400, { code: "ARG-INVALID", msg: "본문이 너무 길어요." });
  await submit(d, "고친 내용 저장");
  expect(d.querySelector("form .ferr")!.textContent).toBe("본문이 너무 길어요.");
});

// 다시 받기 실패(가짜 서버만) — 받아 둔 문맥 그대로 + 못 읽음 안내 · 받아 둔 것이 없으면 = 처음 못 읽음만
const OFF = () => json(503, { code: "OFFLINE", msg: "" });
const partfail = (el: Element) => el.querySelector('[role="alert"].partfail')?.textContent || "";
const failGets = () => serve((url, m) => m === "POST" ? POST(url) : OFF());

test("출처 하나 활동 — 다시 받기 실패 = 받아 둔 활동 그대로 + 못 읽음 안내 · 처음부터 실패 = 못 읽음만", async () => {
  const el = await show("#_obj/source/s1", ["source", "s1", ""]);
  const head = () => el.querySelector(".sechead h3")?.textContent;
  expect(head()).toBe("이 출처의 활동 11");
  expect(el.querySelector(".bars")).not.toBeNull();
  expect(partfail(el)).toBe("");
  failGets();
  await act(async () => { await queryClient.invalidateQueries({ queryKey: ["objects", "source", "s1"] }); });
  await flush();
  expect(queryClient.getQueryState(["objects", "source", "s1"])?.status).toBe("error");
  expect(head()).toBe("이 출처의 활동 11");
  expect(el.querySelector(".bars")).not.toBeNull();
  expect(partfail(el)).toContain("이 출처의 활동을 불러오지 못했어요");
  hideScreen(); queryClient.clear();
  const cold = await show("#_obj/source/s1", ["source", "s1", ""]);
  expect(partfail(cold)).toContain("이 출처의 활동을 불러오지 못했어요");
  expect(cold.querySelector(".sechead")).toBeNull();
});

test("사람 하나 문맥 — 다시 받기 실패 = 받아 둔 활동·글·항목 그대로 + 못 읽음 안내 · 처음부터 실패 = 못 읽음만", async () => {
  const el = await show("#_obj/person/p1", ["person", "p1", ""]);
  const heads = () => [...el.querySelectorAll("h2.sh")].map(h => h.textContent);
  expect(heads()).toEqual(["연결된 활동 3", "연결된 글 1", "이 사람을 가리키는 항목 1"]);
  expect(partfail(el)).toBe("");
  failGets();
  await act(async () => { await queryClient.invalidateQueries({ queryKey: ["objects", "person", "p1"] }); });
  await flush();
  expect(queryClient.getQueryState(["objects", "person", "p1"])?.status).toBe("error");
  expect(heads()).toEqual(["연결된 활동 3", "연결된 글 1", "이 사람을 가리키는 항목 1"]);
  expect(el.querySelector('a[href="#_me/journal/r_sample"]')).not.toBeNull();
  expect(el.querySelector('a[href="#structure/od_principles/i_sample"]')).not.toBeNull();
  expect(partfail(el)).toContain("연결된 활동과 글을 불러오지 못했어요");
  hideScreen(); queryClient.clear();
  const cold = await show("#_obj/person/p1", ["person", "p1", ""]);
  expect(partfail(cold)).toContain("연결된 활동과 글을 불러오지 못했어요");
  expect(cold.querySelector("h2.sh")).toBeNull();
});
