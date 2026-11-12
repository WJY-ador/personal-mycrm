// 모델 목록 나누기(대화 하나로 J-F5), 입력 칸 키(J-F4)
import { expect, test } from "vitest";
import { sendKey } from "./keys";
import { parseModel, splitModels } from "./models";
import type { Choice } from "./store";

const ch = (provider: string, model: string | null, device = "is_1"): Choice => ({ device, provider, model });
const names = (xs: Choice[]) => xs.map(c => c.model);

test("J-F5: 계열마다 가장 새 판 하나만 위에, 나머지는 접는다, PC 가 준 순서 그대로, 목록 밖 모델을 만들지 않는다", () => {
  const list = ["claude-opus-5", "claude-opus-5-5", "claude-sonnet-5-5", "claude-sonnet-4-5-20250929", "claude-haiku-5-5", "claude-haiku-4-5",
    "claude-fable-5-2", "claude-fable-5", "claude-3-5-sonnet-20241022"].map(m => ch("claude", m));
  const { top, rest } = splitModels([ch("claude", null), ...list]);
  expect(names(top)).toEqual([null, "claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5", "claude-fable-5-2"]);
  expect(names(rest)).toEqual(["claude-opus-5", "claude-sonnet-4-5-20250929", "claude-haiku-4-5", "claude-fable-5", "claude-3-5-sonnet-20241022"]);
  expect(top.length + rest.length).toBe(list.length + 1);
});

test("J-F5: 규칙이 못 읽는 이름(별칭, 계열 없음)은 접지 않는다, 공급자와 PC 가 다르면 따로 본다, Codex 도 같은 규칙", () => {
  const { top, rest } = splitModels([ch("claude", "opus"), ch("claude", "sonnet"), ch("claude", "20250101"), ch("codex", "gpt-6-astra"), ch("codex", "gpt-5.6-sol"),
    ch("codex", "gpt-5.5-sol"), ch("claude", "claude-opus-5", "is_2"), ch("claude", "claude-opus-5-5")]);
  expect(names(top)).toEqual(["opus", "sonnet", "20250101", "gpt-6-astra", "gpt-5.6-sol", "claude-opus-5", "claude-opus-5-5"]);
  expect(names(rest)).toEqual(["gpt-5.5-sol"]);
  expect(parseModel("claude", "claude-opus-5-5")).toEqual({ family: "opus", version: [5, 5], date: 0 });
  expect(parseModel("codex", "gpt-5.6-sol")).toEqual({ family: "gpt-sol", version: [5, 6], date: 0 });
  expect(parseModel("claude", null)).toBeNull();
});

test("J-F4(JD4): Enter = 보내기, Shift+Enter = 줄바꿈, 한글 조합 중 Enter(isComposing, keyCode 229) = 보내지 않음", () => {
  const k = (over: Record<string, unknown>) => ({ key: "Enter", shiftKey: false, altKey: false, keyCode: 13, nativeEvent: { isComposing: false }, ...over });
  expect(sendKey(k({}))).toBe(true);
  expect(sendKey(k({ shiftKey: true }))).toBe(false);
  expect(sendKey(k({ altKey: true }))).toBe(false);
  expect(sendKey(k({ nativeEvent: { isComposing: true } }))).toBe(false);
  expect(sendKey(k({ keyCode: 229 }))).toBe(false);
  expect(sendKey(k({ key: "a" }))).toBe(false);
});

test("J-F5: 날짜 꼬리표(8자리)는 판이 아니다 · 같은 계열, 같은 판이면 꼬리표 없는 이름이 위 · 메인 지정 사례", () => {
  const pairs: Array<[string, string, string]> = [   // [provider, 위, 접힘]
    ["claude", "claude-haiku-5-5", "claude-haiku-4-5-20251001"],
    ["claude", "claude-opus-5-5", "claude-opus-5"],
  ];
  for (const [p, up, down] of pairs) {
    for (const order of [[down, up], [up, down]]) {
      const { top, rest } = splitModels(order.map(m => ch(p, m)));
      expect([names(top), names(rest)]).toEqual([[up], [down]]);
    }
  }
  const codex = splitModels([ch("codex", "gpt-5.6-sol"), ch("codex", "gpt-6-astra")]);   // 계열이 달라(gpt-sol, gpt-astra) 둘 다 위
  expect([names(codex.top), names(codex.rest)]).toEqual([["gpt-5.6-sol", "gpt-6-astra"], []]);
  for (const order of [["claude-haiku-4-5-20251001", "claude-haiku-4-5"], ["claude-haiku-4-5", "claude-haiku-4-5-20251001"]]) {
    const { top, rest } = splitModels(order.map(m => ch("claude", m)));
    expect([names(top), names(rest)]).toEqual([["claude-haiku-4-5"], ["claude-haiku-4-5-20251001"]]);
  }
  expect(parseModel("claude", "claude-haiku-4-5-20251001")).toEqual({ family: "haiku", version: [4, 5], date: 20251001 });
});
