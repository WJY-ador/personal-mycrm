// 대화 응답 견본(서버 실제 응답에서 만든 것 — test_tools.py test_chat_samples 가 키·값 타입을 대조) ↔ TS 타입. 타입을 바꾸면 tsc(--noEmit)가 이 줄에서 잡는다.
import { expect, test } from "vitest";
import sample from "./chat.sample.json";
import type { Excluded, Job, Session } from "./types";

const typed = { job: sample.job satisfies Job, session: sample.session satisfies Session, exclude: sample.exclude satisfies Excluded };

test("견본 = 화면이 읽는 모양 — 결과 준비된 작업의 미리보기·세션 복원·제외 뒤 미리보기", () => {
  expect(typed.job.status).toBe("result_ready");
  expect(typed.job.preview!.changes.map(c => c.cid)).toEqual(["c1", "c2"]);
  expect(typed.session.preview!.id).toBe(typed.job.preview!.id);
  expect(typed.exclude.preview.excluded).toEqual(["c2"]);
});
