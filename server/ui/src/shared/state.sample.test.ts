// API 견본 대조(TS 쪽) — 서버 시험(test_web_home.py test_state_sample)이 실제 /api/state 와 대조하는 같은 견본을 AppState 에 묶는다.
// AppState 를 바꾸면 tsc(--noEmit)가 이 줄에서 잡는다.
import { expect, test } from "vitest";
import sample from "./state.sample.json";
import type { AppState } from "./state";

const typed = sample satisfies AppState;

test("견본 = 「나」 화면이 읽는 조각 한 행씩", () => {
  expect(typed.items[0].links.length).toBe(1);
  expect(Object.keys(typed).sort()).toContain("journal_next_before");
});
