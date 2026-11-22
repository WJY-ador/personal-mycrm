// API 견본 대조(TS 쪽) — 서버 시험(test_inbox_digest.py)이 실제 응답과 대조하는 같은 견본을 TS 타입에 묶는다.
import { expect, test } from "vitest";
import type { Digest } from "./collectedApi";
import sample from "./digest.sample.json";

const typed = { with: sample.with satisfies Digest, empty: sample.empty satisfies Digest };

test("견본 = 인박스 요약 있음 · 없음", () => {
  expect(Object.keys(typed.with).sort()).toEqual(["by_axis", "digest", "new_since", "pending_n"]);
  expect(typed.with.digest!.themes[0].item_ids.length).toBe(2);
  expect(typed.empty.digest).toBeNull();
});
