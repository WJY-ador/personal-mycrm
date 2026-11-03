// API 견본 대조(TS 쪽) — 서버 시험(test_web_home.py test_me_samples)이 실제 응답과 대조하는 같은 견본을 meApi 타입에 묶는다.
// Stats·Layout·Journal 을 바꾸면 tsc(--noEmit)가 이 줄에서 잡는다.
import { expect, test } from "vitest";
import sample from "./me.sample.json";
import type { BodyPreview, Journal, Layout, Stats } from "./meApi";

const typed = { stats: sample.stats satisfies Stats, layout: sample.layout satisfies Layout, journal: sample.journal satisfies Journal,
  preview: sample.preview satisfies BodyPreview };

test("견본 = 통계(축·히트맵·종류·기다림) · 레이아웃 v2 · 기록 본문(revision 포함)", () => {
  expect(Object.keys(typed.stats).sort()).toEqual(["axes", "heatmap", "kinds", "waiting"]);
  expect(typed.layout.layout.v).toBe(2);
  expect(typeof typed.journal.revision).toBe("number");
});
