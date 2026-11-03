// API 견본 대조(TS 쪽) — 서버 시험(test_web_import.py test_ui_samples)이 실제 응답과 대조하는 같은 견본을 TS 타입에 묶는다.
// ActList·ActOne·AxisCtx·Agg 를 바꾸면 tsc(--noEmit)가 이 줄에서 잡는다.
import { expect, test } from "vitest";
import type { Agg } from "../../shared/activity";
import type { ActList, ActOne, AxisCtx } from "./actApi";
import sample from "./activity.sample.json";

const typed = sample satisfies { list: ActList; one: ActOne; agg: Agg; axis: AxisCtx };

test("견본 = 목록·하나·현황·축 한 벌씩", () => {
  expect(typed.list.activities.length).toBe(1);
  expect(typed.one.versions[0].current).toBe(true);
  expect(Object.keys(typed.agg)).toContain("undated");
});
