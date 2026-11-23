// 설정 AI 앱 연결(#_setup/connect) — MCP 주소와 [복사], 연결 방법 세 줄(guides/09 1절 표, 주소 = 이 서버 + /mcp), 첫 마디와 [복사], 도움말 링크, 요청 0.
// 복사 줄(shared/CopyRow) — 성공 = 누른 줄에만 복사했어요, 거절이나 지원 안 함 = 직접 골라 복사하라는 한 줄. 결과 자리(role=status)는 처음부터 있다(옛 첫 기록 카드 시험을 옮김)
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { calls, click, installFetch, text } from "../../test/fakeServer";
import { hideScreen, showScreen } from "../../test/showScreen";
import { COPY_FAIL, COPY_OK } from "../../shared/CopyRow";
import { FIRST_SAY } from "./text";

const had = Object.getOwnPropertyDescriptor(navigator, "clipboard");
const setClip = (v: unknown) => Object.defineProperty(navigator, "clipboard", { value: v, configurable: true });
beforeEach(() => { installFetch(); });
afterEach(() => {
  hideScreen();
  vi.unstubAllGlobals();
  if (had) Object.defineProperty(navigator, "clipboard", had); else delete (navigator as { clipboard?: unknown }).clipboard;
});
const show = () => showScreen("connect", "#_setup/connect", []);
const btn = (el: Element, label: string) => el.querySelector(`button[aria-label='${label}']`);
const says = (el: Element) => [...el.querySelectorAll("[role=status]")].map(s => s.textContent);
const URL = location.origin + "/mcp";

test("내용 — 제목, MCP 주소와 복사, 연결 방법 세 줄(이 서버 주소), 첫 마디와 복사, 도움말 링크, 요청 0", async () => {
  const el = await show();
  expect(el.querySelector("h2")!.textContent).toBe("AI 앱 연결");
  expect(el.querySelector("#connect-mcp")!.textContent).toBe(URL);
  expect(el.querySelector("#connect-say")!.textContent).toBe("오늘 있었던 일 기록 남길게.");
  expect(text(el, "button")).toEqual(["복사", "복사"]);
  expect(text(el, "#connect-ways li strong")).toEqual(["Claude (claude.ai)", "Claude Code", "ChatGPT"]);
  const ways = text(el, "#connect-ways li");
  expect(ways[0]).toBe(`Claude (claude.ai): 설정 › 커넥터 › 커스텀 커넥터 추가 → 주소 ${URL} → 로그인 창에서 Google 또는 이메일 코드`);
  expect(ways[1]).toBe(`Claude Code: claude mcp add --transport http my-crm ${URL} 뒤 /mcp 에서 로그인`);
  expect(ways[2]).toContain("Developer Mode 의 커넥터 추가(같은 주소)");
  expect(el.textContent).not.toContain("onrender.com");
  const help = el.querySelector("a[href='/help']");
  expect(help?.textContent).toBe("도움말");
  expect(help?.hasAttribute("target")).toBe(false);
  expect(calls).toEqual([]);
});

test("복사 성공 — 누른 줄에만 복사했어요, 복사한 값 = 화면 글자 그대로", async () => {
  const writeText = vi.fn(async () => {});
  setClip({ writeText });
  const el = await show();
  expect(says(el)).toEqual(["", ""]);
  await click(btn(el, "MCP 주소 복사"));
  expect(writeText).toHaveBeenLastCalledWith(URL);
  expect(says(el)).toEqual([COPY_OK, ""]);
  await click(btn(el, "첫 마디 복사"));
  expect(writeText).toHaveBeenLastCalledWith(FIRST_SAY);
  expect(says(el)).toEqual([COPY_OK, COPY_OK]);
});

test("복사 거절 — 직접 골라 복사하라는 한 줄, 글자는 화면에 그대로", async () => {
  setClip({ writeText: vi.fn(async () => { throw new Error("denied"); }) });
  const el = await show();
  await click(btn(el, "첫 마디 복사"));
  expect(says(el)).toEqual(["", COPY_FAIL]);
  expect(el.querySelector("#connect-say")!.textContent).toBe(FIRST_SAY);
});

test("클립보드 없음 — 같은 안내 한 줄", async () => {
  setClip(undefined);
  const el = await show();
  await click(btn(el, "MCP 주소 복사"));
  expect(says(el)).toEqual([COPY_FAIL, ""]);
  expect(el.querySelector("#connect-mcp")!.textContent).toBe(URL);
});
