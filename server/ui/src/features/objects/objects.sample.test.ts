// API 견본 대조(TS 쪽) — 서버 시험(test_web_import.py test_ui_samples)이 실제 응답과 대조하는 같은 견본을 TS 타입에 묶는다.
// PersonCtx·SourceCtx 를 바꾸면 tsc(--noEmit)가 이 줄에서 잡는다.
import { expect, test } from "vitest";
import type { PersonCtx, SourceCtx } from "./objApi";
import sample from "./objects.sample.json";

const typed = sample satisfies { person: PersonCtx; source: SourceCtx };

test("견본 = 사람·출처 문맥 한 벌씩", () => {
  expect(typed.person.records.length).toBe(1);
  expect(typed.source.by_action[0].n).toBeGreaterThan(0);
});
