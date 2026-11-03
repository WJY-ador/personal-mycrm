// 질문·기록 탭(옛 test_web_home 정적 절의 기록 화면 재검토 표시·축 칩 + 화면 동작, R5b-1) — 질문 고르기 · 한 장(확정·미정·반영 안 함·연결된 글) ·
// [원문과 대조하기] 경로 · 다음 할 일 · 첫 화면 · 기록 탭 출처 필터·원문·축 칩·재검토 · 원문 대화창(인용 mark).
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { queryClient } from "../../shared/queries";
import { calls, click, installFetch, json, serve, text } from "../../test/fakeServer";
import { byText, hideScreen, showScreen } from "../../test/showScreen";
import { JOURNAL, structState } from "../../test/structFixture";

beforeEach(() => { installFetch(); queryClient.clear(); serve(url => (url.startsWith("/api/journal") ? json(200, JOURNAL) : json(404, {}))); });
afterEach(() => { hideScreen(); vi.unstubAllGlobals(); });
const q = (s: object = structState(), blocks = "sheet candidates next", sel = "") => showScreen("sheet", "#q", ["q", "question", blocks, sel], s);

test("질문 한 장 — 고르기 줄(미결정 수) · 확정한 판단 · 아직 안 정한 문장 + 대조 경로 · 반영 안 함 접힘 · 연결된 글", async () => {
  const el = await q();
  expect(text(el, "nav.subtabs a")).toEqual(["Q1 · 도구보다 담당이 먼저인가?1", "Q2 · 두 번째 질문"]);
  expect(el.querySelector("nav.subtabs a.on")!.getAttribute("href")).toBe("#q/q1");
  expect(el.querySelector(".eyebrow")!.textContent).toBe("질문 · Q1");
  expect(text(el, ".sec h3")).toEqual(["확정한 판단1", "아직 안 정한 문장1", "연결된 글1"]);
  expect(el.querySelector(".card.mine .labels")!.textContent).toBe("확정한 판단AI가 쓴 문장");
  expect(el.querySelector(".cta a")!.getAttribute("href")).toBe("#q/review/q1/c2");
  expect(el.querySelector(".cta a")!.textContent).toBe("원문과 대조하기 · 1개");
  expect(el.querySelector("details.fold summary")!.textContent).toBe("반영 안 함 문장 보기 · 1개");
  expect(el.querySelector("details.fold .labels")!.textContent).toBe("내가 쓴 메모 · 내가 고침반영 안 함");
  expect(el.querySelector(".nextline .txt")!.textContent).toBe("기록 1편을 남겨 보세요.");
  expect(el.querySelector(".nextline .say")!.textContent).toContain("「기록 남기자」라고 말하기");
  // 근거 → 원문 대화창(같은 조회 키) — 인용 구간 mark
  await click(el.querySelector(".card.mine .ev a"));
  expect(calls.map(c => c.url)).toEqual(["/api/journal?id=r1"]);
  const dlg = el.querySelector("dialog.recdlg")!;
  expect(dlg.querySelector("#rec-dlg-title")!.textContent).toBe("도입 메모");
  expect(dlg.querySelector("mark")!.textContent).toBe("입력 담당");
  expect(dlg.querySelector("mark strong")!.textContent).toBe("담당");
  expect(dlg.textContent).toContain("블로그 · 웹 주소");
});

test("질문 없음 = 첫 화면 · 고른 질문 · journal 조각 = 최근 글", async () => {
  let el = await q(structState({ questions: [] }));
  expect(el.querySelector(".first h2")!.textContent).toBe("최근에 겪은 일을 한 편 적어볼까요?");
  expect(el.querySelector("nav.subtabs")).toBeNull();
  el = await q(structState(), "journal", "q2");
  expect(el.querySelector("h2.title")!.textContent).toBe("두 번째 질문");
  expect(text(el, ".sec h3")).toEqual(["최근 글2"]);
  expect(el.querySelector(".nextline")).toBeNull();
});

test("부분 읽기 실패 = 그 조각만 못 읽음 표시", async () => {
  const el = await q(structState({ read: { candidates: { ok: false, error: { code: "X", msg: "m" } } } }));
  expect(el.querySelector(".partfail b")!.textContent).toBe("문장 목록을 읽지 못했어요 · 나머지는 정상");
});

test("기록 탭 — 출처 필터(전체 개수) · 원문 · 축 칩 · 재검토 · 다른 글 · 출처 미확인 거르기", async () => {
  const s = structState({ candidates: [{ ...structState().candidates[0], review: "external" }] });
  const el = await showScreen("sheet", "#journal", ["journal", "record", "journal next candidates", ""], s);
  expect(text(el, "nav.srcf a")).toEqual(["전부2", "블로그 · 웹 주소1", "출처 미확인1"]);
  expect(el.querySelector("h2.title")!.textContent).toBe("도입 메모");
  expect(el.querySelector(".labels")!.textContent).toBe("블로그 · 웹 주소붙은 축고객 이해");
  expect(el.querySelector("#recbody .recmeta")!.textContent).toContain("블로그 · 웹 주소");
  expect(el.querySelector("#recbody .doc p")!.textContent).toBe("도입 회의에서 입력 담당을 먼저 정했다.");
  expect(el.querySelector(".recheck")!.textContent).toContain("근거 글이 남이 쓴 글이라");
  expect(el.querySelector(".rside .recs a")!.getAttribute("href")).toBe("#journal/r2");
  await click(byText(el, "nav.srcf a", "출처 미확인1")[0]);
  expect(el.querySelector("h2.title")!.textContent).toBe("회고");
  expect(el.querySelector("nav.srcf a.on")!.getAttribute("aria-pressed")).toBe("true");
  expect(el.querySelector(".rside")).toBeNull();
});
