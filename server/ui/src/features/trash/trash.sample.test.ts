// API 견본 대조(TS 쪽) — 서버 시험(test_trash_flow.py test_trash_sample)이 실제 응답과 대조하는 같은 견본을 TS 타입에 묶는다.
// TrashItem·TrashList 를 바꾸면 tsc(--noEmit)가 이 줄에서 잡는다.
import { expect, test } from "vitest";
import sample from "./trash.sample.json";
import type { TrashList } from "./trashApi";

const typed = sample satisfies TrashList;

test("견본 = 다섯 종류 한 행씩", () => {
  expect(typed.items.map(x => x.kind).sort()).toEqual(["activity", "item", "person", "record", "reflection"]);
});
