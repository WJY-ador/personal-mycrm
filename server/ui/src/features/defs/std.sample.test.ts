// API 견본 대조(TS 쪽) — /api/std/preview 손 사본 견본을 Preview 에 묶는다. 서버 쪽 대조 = server/test_web_home.py test_ui_samples(견본 ⊆ 실제).
import { expect, test } from "vitest";
import sample from "./std.sample.json";
import type { Preview } from "./stdApi";

const typed = sample satisfies Preview;

test("견본 = 편입 카드가 읽는 조각 한 행씩", () => {
  expect(typed.objects[0].lock.changes).toContain("archive");
});
