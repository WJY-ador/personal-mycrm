// API 견본 대조(TS 쪽) — /api/item 손 사본 견본을 ItemFull 에 묶는다. 서버 쪽 대조 = server/test_web_home.py test_ui_samples(견본 ⊆ 실제).
import { expect, test } from "vitest";
import sample from "./item.sample.json";
import type { ItemFull } from "./structApi";

const typed = sample satisfies ItemFull;

test("견본 = 서랍이 읽는 조각 한 행씩", () => {
  expect(typed.targets[0].target_kind).toBe("candidate");
  expect(typed.history[0].action).toBe("apply");
});
