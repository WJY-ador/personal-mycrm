// API 견본 대조(TS 쪽) — 서버 시험(test_web_import.py test_ui_samples)이 실제 응답과 대조하는 같은 견본을 TS 타입에 묶는다.
// Entry·EntryOne·InboxList 를 바꾸면 tsc(--noEmit)가 이 줄에서 잡는다.
import { expect, test } from "vitest";
import type { EntryOne, InboxList } from "./todayApi";
import sample from "./today.sample.json";

const typed = sample satisfies { list: InboxList; one: EntryOne };

test("견본 = 승인 대기 목록·하나", () => {
  expect(typed.list.entries[0].generation?.inputs).toBe(3);
  expect(typed.one.approve_notice).toBeTruthy();
});
