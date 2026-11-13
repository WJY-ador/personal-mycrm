// API 견본 대조(TS 쪽) — 서버 시험(test_collected_inbox.py test_ui_sample)이 실제 응답과 대조하는 같은 견본을 TS 타입에 묶는다.
import { expect, test } from "vitest";
import type { Decided, Dropped, PostList } from "./collectedApi";
import sample from "./collected.sample.json";

const typed = sample satisfies { list: PostList; decided: Decided; dropped: Dropped };

test("견본 = 수집 인박스 목록 · 판별 · 묶음 버림", () => {
  expect(typed.list.posts[0].ai.grade).toBe("signal");
  expect(typed.decided.revision).toBe(2);
});
