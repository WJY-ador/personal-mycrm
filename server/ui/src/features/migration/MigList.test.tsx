// 이관 첫 화면(옛 test_migration_screen.py B1·B4 목록 절을 옮김) — 꺼짐·허용 목록 밖 안내 · 토큰 목록·[폐기] · 발급(확인·한 번만·떠나면 지움·캐시 0) · plan 목록
import { act } from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { queryClient } from "../../shared/queries";
import { calls, click, flush, installFetch, json, serve, text } from "../../test/fakeServer";
import { PID, PLANS, TOKENS } from "../../test/migFixture";
import { byText, cacheText, hideScreen, reload, showScreen } from "../../test/showScreen";

const SECRET = "mig_mt_0123456789abcdef.SECRET";
let tok: object = TOKENS, plans: object = PLANS, post: (url: string) => Response = () => json(200, { token: SECRET, info: { label: "이관 업로더" } });
const confirm = vi.fn((_ask?: string) => true);

beforeEach(() => {
  installFetch(); queryClient.clear(); reload.mockClear(); confirm.mockClear(); confirm.mockReturnValue(true);
  vi.stubGlobal("confirm", confirm);
  tok = TOKENS; plans = PLANS;
  serve((url, m) => m === "POST" ? post(url) : url === "/api/migration-tokens" ? json(200, tok) : url === "/api/migrations" ? json(200, plans) : json(404, { code: "NOT-FOUND" }));
});
afterEach(() => { hideScreen(); vi.unstubAllGlobals(); });
const list = () => showScreen("migration", "#_setup/migration", [""]);

test("꺼짐·허용 목록 밖 = [새 토큰] 대신 안내 · [폐기]는 그대로", async () => {
  for (const [sw, say] of [[{ enabled: false }, "운영자가 켜면"], [{ allowed: false }, "허용 목록에 없어요"]] as const) {
    tok = { ...TOKENS, ...sw };
    const el = await list();
    expect(el.textContent).toContain(say);
    expect(el.textContent).toContain("이관이 켜지면 여기서 새 토큰을 발급해요.");
    expect(byText(el, "button", "새 토큰")).toEqual([]);
    expect(byText(el, "button", "폐기").length).toBe(1);
    hideScreen(); queryClient.clear();
  }
});

test("켜짐 = 토큰 목록(상태·만료·마지막 사용) · 살아 있는 토큰만 [폐기] · plan 목록(상태·항목 수·만료·사용량/한도·대화에서 반영됨)", async () => {
  const el = await list();
  const t = el.textContent!;
  for (const w of ["사용 중", "폐기됨", "이관 업로더", "옛 업로더", "11월 16일 10:00 만료", "마지막 사용 아직 없음", "마지막 사용 10월 21일 10:00",
    "새로 발급하면 이전 토큰은 폐기돼요.", "14일 뒤 만료돼요", "오늘 반영 7 / 200행", "plan당 200항목", "열린 plan 3개까지", "보관 3일",
    "확인 대기", "반영함", "8항목", "11월 5일 10:00 만료", "새로 넣기 5 · 중복 의심 2 · 거절 1", "영수증 보기"]) expect(t).toContain(w);
  expect(byText(el, "button", "폐기").length).toBe(1);
  expect(el.querySelector(`a[href="#_setup/migration/${PID}"]`)).not.toBeNull();
  expect(text(el, ".badge")).toEqual(["대화에서 반영됨"]);
});

test("발급 — 앞 토큰 있으면 확인 → 한 번만 보임(캐시 0) → [지우기]·plan 으로 가면 지움", async () => {
  let el = await list();
  await click(byText(el, "button", "새 토큰")[0]);
  expect(confirm.mock.calls[0][0]).toContain("이전 토큰은 폐기돼요");
  expect(calls.filter(c => c.method === "POST")).toEqual([{ url: "/api/migration-tokens", method: "POST", body: {} }]);
  expect((el.querySelector('input[aria-label="이관 토큰"]') as HTMLInputElement).value).toBe(SECRET);
  expect(el.textContent).toContain("「이관 업로더」 이관 토큰 — 지금 한 번만 보여요");
  expect(el.textContent).toContain("새 이관 토큰을 발급했어요. 지금 옮겨 두세요.");
  expect(reload).toHaveBeenCalledTimes(1);
  expect(cacheText()).not.toContain("SECRET");
  await click(byText(el, "button", "붙여 넣었어요 · 지우기")[0]);
  expect(el.outerHTML).not.toContain("SECRET");
  await click(byText(el, "button", "새 토큰")[0]);
  expect(el.outerHTML).toContain("SECRET");
  serve((url, m) => json(200, m === "GET" && url.includes(PID) ? { ...PLANS.plans[0], counts: { actions: {}, units: {} }, items: [] } : url === "/api/migrations" ? plans : tok));
  el = await showScreen("migration", `#_setup/migration/${PID}`, [PID]);
  expect(el.outerHTML).not.toContain("SECRET");
  el = await list();
  expect(el.outerHTML).not.toContain("SECRET");
});

test("꺼지면 받은 토큰도 그리지 않음 · 앞 토큰 없으면 확인 없이 발급 · 실패 = 스위치 문구", async () => {
  tok = { ...TOKENS, tokens: [TOKENS.tokens[1]] };
  let el = await list();
  await click(byText(el, "button", "새 토큰")[0]);
  expect(confirm).not.toHaveBeenCalled();
  expect(el.outerHTML).toContain("SECRET");
  tok = { ...tok, enabled: false };
  await queryClient.invalidateQueries();
  el = await list();
  expect(el.outerHTML).not.toContain("SECRET");
  hideScreen(); queryClient.clear();
  tok = { ...TOKENS, tokens: [] };
  post = () => json(403, { code: "MIGRATION-OFF", msg: "x" });
  el = await list();
  await click(byText(el, "button", "새 토큰")[0]);
  expect(text(el, ".ferr")).toContain("지금은 이관이 꺼져 있어요.");
  post = () => json(200, { token: SECRET, info: { label: "이관 업로더" } });
});

test("[폐기] — 확인 안 함 = 요청 0 · 확인 = revoke 1", async () => {
  const el = await list();
  confirm.mockReturnValue(false);
  await click(byText(el, "button", "폐기")[0]);
  expect(calls.filter(c => c.method === "POST")).toEqual([]);
  confirm.mockReturnValue(true);
  await click(byText(el, "button", "폐기")[0]);
  expect(calls.filter(c => c.method === "POST")).toEqual([{ url: "/api/migration-tokens/mt_a/revoke", method: "POST", body: {} }]);
  expect(el.textContent).toContain("이관 토큰을 폐기했어요.");
});

test("다시 받기 실패 — 받아 둔 토큰·plan 목록은 그대로 + 실패한 조각만 오류 알림(exact 키 무효화)", async () => {
  for (const [key, url, what] of [[["mig", "tokens"], "/api/migration-tokens", "이관 토큰을"], [["mig", "plans"], "/api/migrations", "이관 plan 목록을"]] as const) {
    const el = await list();
    expect(el.querySelector(".partfail")).toBeNull();   // 처음엔 불러오기 오류 없음(폼의 빈 role=alert 칸은 세지 않는다)
    serve((u, m) => u === url && m === "GET" ? json(500, { code: "SERVER-ERROR", msg: "가짜 실패" })
      : u === "/api/migration-tokens" ? json(200, tok) : u === "/api/migrations" ? json(200, plans) : json(404, { code: "NOT-FOUND" }));
    calls.length = 0;
    await act(async () => { await queryClient.invalidateQueries({ queryKey: [...key], exact: true }); });
    await flush();
    expect(calls.map(c => c.url)).toEqual([url]);   // exact = 그 키 하나만 다시 받는다
    const t = el.textContent!;
    for (const w of ["이관 업로더", "옛 업로더", "오늘 반영 7 / 200행", "pc-test-1", "확인 대기", "영수증 보기"]) expect(t).toContain(w);
    expect(text(el, ".partfail b")).toEqual([`${what} 불러오지 못했어요 · 나머지는 정상`]);
    expect(text(el, ".partfail code")).toEqual(["SERVER-ERROR"]);
    hideScreen(); queryClient.clear();
    serve((u, m) => m === "POST" ? post(u) : u === "/api/migration-tokens" ? json(200, tok) : u === "/api/migrations" ? json(200, plans) : json(404, { code: "NOT-FOUND" }));
  }
});
