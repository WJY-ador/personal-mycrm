// API 견본 대조(TS 쪽) — 서버 시험(test_routine_board.py)이 실제 응답과 대조하는 같은 견본을 meApi 타입에 묶는다. Routine·RoutineDetail 을 바꾸면 tsc 가 잡는다.
import { expect, test } from "vitest";
import sample from "./routine.sample.json";
import type { Routine, RoutineDetail } from "./meApi";

const typed = { board: sample.board satisfies Routine, detail: sample.detail satisfies RoutineDetail };

test("견본 = 루틴판 집계(세 열·since) · 한판 상세(소제목·출처)", () => {
  expect(Object.keys(typed.board).sort()).toEqual(["decided", "in", "last_routine_at", "missing", "ready", "since", "writing"]);
  expect(Object.keys(typed.detail).sort()).toEqual(["board", "decided", "inflow", "missing_sources", "subheads"]);
  expect(typed.detail.inflow[0].kind).toBe("post");
});
