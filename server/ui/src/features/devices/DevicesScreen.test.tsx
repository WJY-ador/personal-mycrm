// Setup 「연결 장치」(옛 test_web_import.py·test_download.py 의 app.html 정적 절을 옮김) — PC 앱 설치 링크 하나 · 장치 카드 · 새 장치(빈 이름 막음) ·
// 토큰 한 번만(캐시 0 · [지우기]·떠나면 지움) · 재발급·해제 확인 · 허용 규칙 = expected_revision · 실패 문구
import { act } from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { queryClient } from "../../shared/queries";
import { calls, click, installFetch, json, serve, text } from "../../test/fakeServer";
import { byText, cacheText, hideScreen, reload, showScreen } from "../../test/showScreen";
import { type } from "../../test/showMe";
import sample from "./devices.sample.json";

const SECRET = "imp_0123.SECRET";
const D = sample.devices[0];
const LIST = { ...sample, active: 2, max: 5, devices: [{ ...D, id: "d1", label: "집 노트북", policy: { actions: ["like"], transform_versions: ["board-likes/1"], axes: ["a1"] }, policy_revision: 3 },
  { ...D, id: "d2", label: "옛 PC", active: false, revoked_at: "2026-10-01T01:00:00+00:00" }] };
const S = { items: [{ id: "a1", object_id: sample.choices.axis_object_id, title: "고객 이해" }, { id: "a2", object_id: sample.choices.axis_object_id, title: "실행 속도" }],
  activity_ui: { actions: { like: "좋아요" } }, switches: {} };
let post: (url: string) => Response = () => json(200, { token: SECRET, device: { label: "새 PC" } });
const confirm = vi.fn((_ask?: string) => true);
const show = () => showScreen("devices", "#_setup/devices", [], S);
const posts = () => calls.filter(c => c.method === "POST");

beforeEach(() => {
  installFetch(); queryClient.clear(); reload.mockClear(); confirm.mockReturnValue(true);
  vi.stubGlobal("confirm", confirm);
  post = () => json(200, { token: SECRET, device: { label: "새 PC" } });
  serve((url, m) => (m === "POST" ? post(url) : json(200, LIST)));
});
afterEach(() => { hideScreen(); vi.unstubAllGlobals(); });

test("안내 · PC 앱 설치 링크 하나(/download) · 이관 링크 · 장치 카드(상태·날짜·허용 규칙 한 줄) · 해제한 장치 = 버튼 없음", async () => {
  const el = await show();
  expect(el.querySelectorAll('a[href="/download"]').length).toBe(1);
  expect(el.querySelector('a[href="#_setup/migration"]')!.textContent).toBe("이관");
  expect(text(el, "article h3")).toEqual(["집 노트북", "옛 PC"]);
  expect(text(el, "article .chip")).toEqual(["연결됨", "연결 해제됨"]);
  expect(el.textContent).toContain("행동 좋아요 · 받는 것 좋아요 활동(바로 저장) · 축 1개");
  expect(el.textContent).toContain("연결 2 / 5");
  expect(byText(el, "article button", "토큰 재발급").length).toBe(1);
  expect(el.textContent).toContain("해제한 장치는 되살리지 않아요");
});

test("새 장치 — 빈 이름 = 요청 0 · 연결 = 토큰 한 번만(캐시·결과 문구에 없음) → [지우기] · 화면을 떠나면 지움", async () => {
  let el = await show();
  await click(byText(el, "button", "연결하기")[0]);
  expect(posts()).toEqual([]);
  expect(text(el, "form .ferr")[0]).toBe("장치 이름을 적어 주세요.");
  await type(el.querySelector("#dev-label") as HTMLInputElement, "  새 PC ");
  await click(byText(el, "button", "연결하기")[0]);
  expect(posts()).toEqual([{ url: "/api/devices", method: "POST", body: { label: "새 PC" } }]);
  expect((el.querySelector('input[aria-label="토큰"]') as HTMLInputElement).value).toBe(SECRET);
  expect(el.textContent).toContain("「새 PC」 토큰 — 지금 한 번만 보여요");
  expect(text(el, "p.fok")[0]).toBe("장치를 연결했어요. 토큰을 지금 옮겨 두세요.");
  expect(cacheText()).not.toContain("SECRET");
  expect(reload).toHaveBeenCalledTimes(1);
  await click(byText(el, "button", "붙여 넣었어요 · 지우기")[0]);
  expect(el.outerHTML).not.toContain("SECRET");
  await click(byText(el, "button", "토큰 재발급")[0]);
  expect(confirm.mock.calls[0][0]).toContain("지금 토큰은 바로 쓸 수 없게 돼요");
  expect(el.outerHTML).toContain("SECRET");
  hideScreen();
  el = await show();
  expect(el.outerHTML).not.toContain("SECRET");
});

test("재발급·해제 — 확인 안 함 = 요청 0 · 해제 = revoke · 허용 규칙 저장 = 고른 값 + expected_revision", async () => {
  const el = await show();
  confirm.mockReturnValue(false);
  await click(byText(el, "button", "연결 해제")[0]);
  expect(posts()).toEqual([]);
  confirm.mockReturnValue(true);
  post = () => json(200, {});
  await click(byText(el, "button", "연결 해제")[0]);
  expect(posts()).toEqual([{ url: "/api/devices/d1/revoke", method: "POST", body: {} }]);
  expect(text(el, "p.fok")[0]).toBe("연결을 해제했어요.");
  calls.length = 0;
  const ax2 = el.querySelector('input[name="axes"][value="a2"]') as HTMLInputElement;
  await act(async () => { ax2.click(); });
  await click(byText(el, "button", "허용 규칙 저장")[0]);
  expect(posts()).toEqual([{ url: "/api/devices/d1/policy", method: "POST",
    body: { policy: { actions: ["like"], transform_versions: ["board-likes/1"], axes: ["a1", "a2"] }, expected_revision: 3 } }]);
  expect(text(el, "p.fok")[0]).toBe("허용 규칙을 바꿨어요. 다음 업로드부터 적용돼요.");
});

test("실패 — 충돌 = 머리 문구 + 다시 받기 · 그 밖 = 그 자리에 서버 문구", async () => {
  const el = await show();
  post = () => json(409, { code: "CONFLICT", msg: "x" });
  await click(byText(el, "button", "허용 규칙 저장")[0]);
  expect(text(el, "p.fok.bad")).toEqual(["다른 곳에서 먼저 바뀌었어요. 다시 불러왔어요 — 확인하고 다시 해 주세요."]);
  expect(reload).toHaveBeenCalledTimes(1);
  post = () => json(400, { code: "DEVICE-LIMIT", msg: "장치는 5대까지예요." });
  await type(el.querySelector("#dev-label") as HTMLInputElement, "또 PC");
  await click(byText(el, "button", "연결하기")[0]);
  expect(text(el, "form .ferr")[0]).toBe("장치는 5대까지예요.");
});
