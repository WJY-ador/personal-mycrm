// API 견본 대조(TS 쪽) — 서버 시험(test_migration_screen.py test_ui_samples)이 실제 응답과 대조하는 같은 견본을 이관 타입에 묶는다.
import { expect, test } from "vitest";
import type { Detail, ItemBody, Plans, Receipt, Tokens } from "./migApi";
import sample from "./migration.sample.json";

const typed = sample satisfies { tokens: Tokens; plans: Plans; detail: Detail; item: ItemBody; receipt: Receipt };

test("견본 = 토큰·plan 목록·확인·본문·영수증 한 벌씩", () => {
  expect(typed.detail.state).toBe("sealed");
  expect(typed.receipt.items[0].stored_hash).toBe(typed.receipt.items[0].content_hash);
});
