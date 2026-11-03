// plan 하나(옛 test_migration_screen.py B2·B3·B4 를 옮김) — 확인 화면(표·항목·사유·체크 상자) · 체크 = seqs 하나 · 확인창 숫자 · 반영 = plan_hash ·
// 취소 · seal 전/만료 · 꺼짐 · 오류 문구 · 본문 펼침(하나씩·글자 그대로) · 영수증(해시 일치/다름/휴지통)
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { queryClient } from "../../shared/queries";
import { calls, click, installFetch, json, serve, text } from "../../test/fakeServer";
import { DETAIL, PID, PLANS, RECEIPT, TOKENS } from "../../test/migFixture";
import { byText, cacheText, hideScreen, reload, showScreen } from "../../test/showScreen";

let detail: object = DETAIL, plans: object = PLANS, post: (url: string) => Response = () => json(200, {});
let item: (seq: number) => Response = seq => json(200, { seq, payload: { unit_kind: "record", title: "제목", body: "본문 <b>전문</b>\n둘째 줄", author_kind: "self",
  text_process: "verbatim", generation_kind: "human", primary_date: { kind: "written", value: "2025-03-01" }, review: { state: "reviewed" }, sensitivity: "normal" } });
const confirm = vi.fn((_ask?: string) => true);
const show = () => showScreen("migration", `#_setup/migration/${PID}`, [PID]);
const posts = () => calls.filter(c => c.method === "POST");

beforeEach(() => {
  installFetch(); queryClient.clear(); reload.mockClear(); confirm.mockReturnValue(true);
  vi.stubGlobal("confirm", confirm);
  detail = DETAIL; plans = PLANS; post = () => json(200, {});
  serve((url, m) => {
    if (m === "POST") return post(url);
    const s = /\/items\/(\d+)$/.exec(url);
    if (s) return item(Number(s[1]));
    if (url.endsWith("/receipt")) return json(200, RECEIPT);
    if (url === "/api/migrations") return json(200, plans);
    if (url === "/api/migration-tokens") return json(200, TOKENS);
    return json(200, detail);
  });
});
afterEach(() => { hideScreen(); vi.unstubAllGlobals(); });

test("확인 화면 — 자료군 표 · 항목 · 사유 · 기준마다 체크 상자 · 항목마다 [본문 보기] · 확인창 숫자", async () => {
  const el = await show();
  const t = el.textContent!;
  for (const w of ["자료군별 개수", "principle_c", "합계", "#0", "첫 기록", "새로 넣기", "이미 있음", "중복 의심", "충돌", "거절",
    "사유 · 같은 내용이 다른 ID 로 있음", "duplicate_content", "사유 · 내부 자료(internal)", "(본문을 지웠어요)",
    "항목 8개 · 기준 체크 1 / 3", "이 기준을 반영할게요", "오늘 남은 이관 한도 193행"]) expect(t).toContain(w);
  const boxes = [...el.querySelectorAll<HTMLInputElement>('input[type="checkbox"]')];
  expect(boxes.map(b => [b.dataset.seq, b.checked])).toEqual([["2", true], ["3", false], ["4", false]]);
  expect(byText(el, "button", "본문 보기").length).toBe(8);
  const dlg = el.querySelector("dialog")!.textContent!;
  for (const w of ["새로 넣을 항목 3개", "이미 있어 그대로 둘 항목 0개", "체크 안 한 기준 2개 — 반영하지 않아요", "중복 의심 1 · 충돌 1 · 거절 1개 — 반영하지 않아요",
    "오늘 남은 이관 한도 193행"]) expect(dlg).toContain(w);
  for (const w of ["전체 선택", "모두 체크", "모두 선택"]) expect(t).not.toContain(w);   // 일괄 체크 없음
});

test("체크 = 상자 하나에 요청 하나(seqs 하나) · 응답 = 새 plan 으로 다시 그림", async () => {
  post = () => json(200, { ...DETAIL, items: DETAIL.items.map(x => (x.seq === 3 ? { ...x, checked: true } : x)) });
  const el = await show();
  await click(el.querySelector('input[data-seq="3"]'));
  expect(posts()).toEqual([{ url: `/api/migrations/${PID}/check`, method: "POST", body: { seqs: [3], checked: true } }]);
  expect(el.textContent).toContain("기준 체크 2 / 3");
  expect(el.querySelector("dialog")!.textContent).toContain("새로 넣을 항목 4개");
});

test("반영 = plan_hash · 결과 한 줄 + 상태 다시 받기 · 두 번째 = 같은 영수증 문구 · 취소(확인 안 함 = 0, 확인 = cancel → 목록)", async () => {
  post = () => json(200, { already_applied: false });
  const el = await show();
  await click(byText(el, "dialog button", "반영")[0]);
  expect(posts()).toEqual([{ url: `/api/migrations/${PID}/apply`, method: "POST", body: { plan_hash: "b".repeat(64) } }]);
  expect(el.textContent).toContain("반영했어요. 영수증을 확인하세요.");
  expect(reload).toHaveBeenCalledTimes(1);
  post = () => json(200, { already_applied: true });
  await click(byText(el, "dialog button", "반영")[0]);
  expect(el.textContent).toContain("이미 반영한 plan이에요. 같은 영수증을 보여 줘요.");
  calls.length = 0; confirm.mockReturnValue(false);
  await click(byText(el, "button", "이 plan 취소")[0]);
  expect(posts()).toEqual([]);
  confirm.mockReturnValue(true); post = () => json(200, {});
  await click(byText(el, "button", "이 plan 취소")[0]);
  expect(confirm.mock.calls.at(-1)![0]).toContain("올린 본문을 바로 지우고 되돌릴 수 없어요");
  expect(posts()).toEqual([{ url: `/api/migrations/${PID}/cancel`, method: "POST", body: {} }]);
  expect(location.hash).toBe("#_setup/migration");
});

test("seal 전 = 안내 + [취소]만 · 만료 = 닫힌 안내 + 표 · 꺼짐 = 체크·[반영]·확인창 0, [취소]·본문 보기 그대로", async () => {
  detail = { ...DETAIL, state: "staged", plan_hash: null, items: [] };
  let el = await show();
  expect(el.textContent).toContain("seal 전");
  expect(el.querySelectorAll('input[type="checkbox"]').length).toBe(0);
  hideScreen(); queryClient.clear();
  detail = { ...DETAIL, state: "expired", closed_at: "2026-11-05T01:00:00+00:00" };
  el = await show();
  expect(el.textContent).toContain("보관 기간이 지나 닫힌 plan이에요");
  expect(byText(el, "button", "반영")).toEqual([]);
  hideScreen(); queryClient.clear();
  detail = DETAIL; plans = { ...PLANS, enabled: false };
  el = await show();
  expect(el.querySelectorAll('input[type="checkbox"]').length).toBe(0);
  expect(el.querySelector("dialog")).toBeNull();
  expect(byText(el, "button", "반영")).toEqual([]);
  expect(byText(el, "button", "이 plan 취소").length).toBe(1);
  expect(byText(el, "button", "본문 보기").length).toBe(8);
  expect(el.textContent).toContain("기준 체크와 반영을 할 수 없어요");
});

test("오류 — 사람 말 문구(코드는 기술 정보) · PLAN-STALE 바뀐 항목 · CHECK-DEPENDENCY 줄 링크 · RATE-LIMIT 재개 시각 · NAME-REQUIRED = 머리 문구 + 다시 받기", async () => {
  const el = await show();
  const fail = async (status: number, j: object) => { post = () => json(status, j); await click(byText(el, "dialog button", "반영")[0]); return el.querySelector("#mig-err")!.textContent!; };
  let t = await fail(409, { code: "PLAN-STALE", msg: "서버", detail: { changed: [{ seq: 0, sealed: "insert", now: "noop" }, { seq: 7, sealed: "insert", now: "reject", reason: "ref-not-found" }] } });
  for (const w of ["아무것도 반영하지 않았어요", "#0 첫 기록 — 새로 넣기 → 이미 있음", "#7 기준에 붙는 기록 — 새로 넣기 → 거절", "가리키는 항목을 찾을 수 없음", "취소한 뒤 PC에서 다시 올려 주세요", "PLAN-STALE"])
    expect(t).toContain(w);
  t = await fail(409, { code: "PLAN-HASH-MISMATCH", msg: "x" });
  expect(t).toContain("서버에 저장한 plan이 달라요");
  t = await fail(429, { code: "RATE-LIMIT", msg: "x", resume_at: "2026-11-02T15:00:00+00:00", detail: { needed: 230 } });
  expect(t).toContain("(230행)"); expect(t).toContain("11월 3일 00:00 이후에 다시 반영해 주세요");
  t = await fail(409, { code: "CHECK-DEPENDENCY", msg: "x", detail: { seqs: [7] } });
  expect(t).toContain("체크하지 않은 기준을 가리키는 항목"); expect(text(el, "#mig-err a")).toEqual(["#7 기준에 붙는 기록"]);
  t = await fail(409, { code: "PLAN-EXPIRED", msg: "x" });
  expect(t).toContain("보관 기간(3일)이 지나");
  t = await fail(400, { code: "SOMETHING", msg: "서버 문구" });
  expect(t).toContain("서버 문구");
  reload.mockClear();
  await fail(403, { code: "NAME-REQUIRED", msg: "이름" });
  expect(reload).toHaveBeenCalledTimes(1);
  expect(text(el, "p.fok.bad")).toEqual(["이름"]);
});

test("본문 — 펼칠 때 하나씩 받음 · 글자 그대로(태그 아님) · 접고 다시 펴면 요청 0 · 실패 = 다시 열면 다시 받음 · 캐시 0", async () => {
  const el = await show();
  await click(byText(el, "button", "본문 보기")[0]);
  const box = el.querySelector("#mig-b-0")!;
  expect(box.textContent).toContain("본문 <b>전문</b>");
  expect(box.querySelector("b")).toBeNull();
  expect(box.textContent).toContain("받은 그대로(JSON)");
  expect(cacheText()).not.toContain("전문");
  await click(byText(el, "button", "본문 접기")[0]);
  await click(byText(el, "button", "본문 보기")[0]);
  expect(calls.filter(c => c.url.includes("/items/")).map(c => c.url)).toEqual([`/api/migrations/${PID}/items/0`]);
  item = seq => (seq === 5 ? json(500, {}) : json(200, { seq, payload: null }));
  await click(el.querySelector('button[data-body="5"]'));
  expect(el.querySelector("#mig-b-5")!.textContent).toContain("본문을 불러오지 못했어요");
  await click(el.querySelector('button[data-body="5"]')); await click(el.querySelector('button[data-body="5"]'));
  expect(calls.filter(c => c.url.endsWith("/items/5")).length).toBe(2);
  await click(el.querySelector('button[data-body="6"]'));
  expect(el.querySelector("#mig-b-6")!.textContent).toContain("본문은 지웠어요");
});

test("영수증 — 결과별 개수 · 항목별 결과·대상 id · 해시 일치/다름/휴지통", async () => {
  detail = { ...DETAIL, state: "applied" };
  const el = await show();
  const t = el.textContent!;
  for (const w of ["이관 영수증", "import_batch_id", "receipt_hash", "결과별 개수", "반영함", "체크 안 함", "거절 · 건너뜀", "본문 해시 대조", "1 / 3 일치", "휴지통에 있음", "r_1", "i_1", "o_4"])
    expect(t).toContain(w);
  expect(text(el, ".chip.st-mine")).toContain("일치");
  expect(text(el, ".chip.flag")).toEqual(["다름"]);
});
