// 「나」 쓰기 — 수기 수정(항목 제목·본문 [저장] 1번 · 내 글 제목·본문) + 기존 편집(표시 이름·읽고 든 생각·고쳐서 남기기).
// 쓰기는 [저장]을 눌렀을 때만(입력·취소·Esc = 요청 0) · 고친 동안 setDirty(주소) · 실패 = 서버 msg·action 그대로 · CONFLICT = 다시 받기.
import { act } from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { queryClient } from "../../shared/queries";
import { calls, click, flush, installFetch, json, serve } from "../../test/fakeServer";
import { installMedia, JOURNAL, layout, meState, STATS } from "../../test/meFixture";
import { btn, hideMe, reload, setDirty, showMe, type } from "../../test/showMe";

let POST: (url: string) => Response = () => json(200, {});
beforeEach(() => {
  installFetch(); installMedia(false); queryClient.clear(); reload.mockClear(); setDirty.mockClear();
  POST = () => json(200, {});
  serve((url, m) => {
    if (m === "POST") return POST(url);
    if (url === "/api/me/layout") return json(200, layout());
    if (url === "/api/me/stats") return json(200, STATS);
    if (url.startsWith("/api/journal?id=")) return json(200, JOURNAL);
    return json(200, { activities: [], activity_count: 0 });
  });
});
afterEach(() => { hideMe(); vi.unstubAllGlobals(); });
const posts = () => calls.filter(c => c.method === "POST");
const input = (el: Element, id = "hedit-input") => el.querySelector<HTMLInputElement & HTMLTextAreaElement>("#" + id)!;
const save = (el: Element) => click(el.querySelector("form button[type=submit]"));

test("항목 — 제목을 누르면 제목·본문 한 칸 · 입력 = 요청 0 · setDirty(주소) · [저장] 1번 = /api/item/edit · 성공 = 다시 받기 + 문구", async () => {
  const el = await showMe("#_me/principle/p1", meState());
  await click(el.querySelector("#home-detail h2 button"));
  expect(input(el).value).toBe("담당이 먼저");
  expect(input(el, "hedit-body").value).toBe("본문 **굵게**");
  await type(input(el), "담당이 먼저다");
  await type(input(el, "hedit-body"), "고친 본문");
  expect(posts()).toEqual([]);
  expect(setDirty).toHaveBeenLastCalledWith("#_me/principle/p1");
  await save(el);
  expect(posts()).toEqual([{ url: "/api/item/edit", method: "POST", body: { item_id: "p1", expected_revision: 2, title: "담당이 먼저다", body: "고친 본문" } }]);
  expect(reload).toHaveBeenCalledTimes(1);
  expect(el.textContent).toContain("저장했어요.");
  expect(setDirty).toHaveBeenLastCalledWith(null);
});

test("항목 저장 실패 = 서버 msg·action 그대로(화면이 문구를 짓지 않음) · CONFLICT 면 다시 받기 · 편집 칸 유지", async () => {
  const el = await showMe("#_me/principle/p1", meState());
  await click(el.querySelector("#home-detail h2 button"));
  await type(input(el), "새 제목");
  POST = () => json(400, { code: "CONFLICT", msg: "다른 곳에서 먼저 바뀌었어요 (지금 revision 3)", action: "다시 읽고 하세요." });
  await save(el);
  expect(el.querySelector("#hedit-err")!.textContent).toBe("다른 곳에서 먼저 바뀌었어요 (지금 revision 3) 다시 읽고 하세요.");
  expect(reload).toHaveBeenCalledTimes(1);
  expect(input(el).value).toBe("새 제목");
});

test("취소·Esc = 요청 0 · 바뀐 게 없으면 [저장]도 요청 0 · 빈 제목 = 안내", async () => {
  const el = await showMe("#_me/principle/p1", meState());
  await click(el.querySelector("#home-detail h2 button"));
  await save(el);
  expect(posts()).toEqual([]);
  expect(el.querySelector("form")).toBeNull();
  await click(el.querySelector("#home-detail h2 button"));
  await type(input(el), " ");
  await save(el);
  expect(el.querySelector("#hedit-err")!.textContent).toBe("비어 있어요. 내용을 적은 뒤 저장해 주세요.");
  await act(async () => { input(el).dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true })); });
  expect(el.querySelector("form")).toBeNull();
  await click(el.querySelector("#home-detail h2 button"));
  await click(btn(el, "취소"));
  expect(el.querySelector("form")).toBeNull();
  expect(posts()).toEqual([]);
});

test("내 글 제목 = /api/records/{id}/title(revision = 본문 응답) · 본문 = 새 본문 전체를 /body 로", async () => {
  const el = await showMe("#_me/journal/r1", meState());
  await click(el.querySelector("#home-detail h2 button"));
  await type(input(el), "새 제목");
  await save(el);
  expect(posts().at(-1)).toEqual({ url: "/api/records/r1/title", method: "POST", body: { expected_revision: 4, title: "새 제목" } });
  await click(el.querySelector(".doc")!.closest("[role=button]"));
  expect(input(el).value).toBe(JOURNAL.body);
  await type(input(el), JOURNAL.body.replace("둘째", "두 번째"));
  await save(el);
  expect(posts().at(-1)).toEqual({ url: "/api/records/r1/body", method: "POST", body: { expected_revision: 4, body: JOURNAL.body.replace("둘째", "두 번째") } });
  expect(el.textContent).toContain("본문을 고쳤어요.");
});

test("내 글 본문 막힘(RECORD-LOCKED) = 서버 msg·action 그대로 · 다시 받지 않음", async () => {
  const el = await showMe("#_me/journal/r1", meState());
  await click(el.querySelector(".doc")!.closest("[role=button]"));
  await type(input(el), "다른 본문");
  POST = () => json(400, { code: "RECORD-LOCKED", msg: "내가 결정한 판단(남기기·남기지 않기) 1개가 붙은 글이라 본문을 고칠 수 없어요.", action: "고친 글은 새 기록으로 남기세요(record_add)." });
  await save(el);
  expect(el.querySelector("#hedit-err")!.textContent).toBe("내가 결정한 판단(남기기·남기지 않기) 1개가 붙은 글이라 본문을 고칠 수 없어요. 고친 글은 새 기록으로 남기세요(record_add).");
  expect(reload).not.toHaveBeenCalled();
});

test("남이 쓴 글 = 제목·본문 고치기 없음", async () => {
  serve(url => (url.startsWith("/api/journal") ? json(200, { ...JOURNAL, author_kind: "external" }) : json(200, layout())));
  const el = await showMe("#_me/journal/r1", meState({ journal: [{ ...meState().journal[0], author_kind: "external" }] }));
  expect(el.querySelector("#home-detail h2 button")).toBeNull();
  expect(el.querySelector("[role=button]")).toBeNull();
  expect(el.querySelector(".doc")).toBeTruthy();
});

test("기존 편집 — 표시 이름 · 읽고 든 생각(저장 = 확인 전) · 고쳐서 남기기", async () => {
  let el = await showMe("#_me/summary", meState());
  await click(el.querySelector(".hhead button"));
  await type(input(el), "새 이름");
  await save(el);
  expect(posts().at(-1)).toEqual({ url: "/api/me/name", method: "POST", body: { display_name: "새 이름" } });
  el = await showMe("#_me/refl/f1", meState());
  await click(el.querySelector("#home-detail button[title='눌러서 고치기']"));
  await type(input(el), "고친 생각");
  await save(el);
  expect(posts().at(-1)).toEqual({ url: "/api/reflections/f1", method: "POST", body: { source_id: "s1", kind: "summary", body: "고친 생각", expected_revision: 2 } });
  el = await showMe("#_me/cand/c1", meState());
  await click(btn(el, "고쳐서 남기기"));
  await type(input(el), "고친 판단");
  await save(el);
  expect(posts().at(-1)).toEqual({ url: "/api/candidate/decide", method: "POST", body: { candidate_id: "c1", action: "edit_confirm", text: "고친 판단", expected_revision: 1 } });
  await flush();
});
