// API 견본 대조(TS 쪽) — 서버 시험(test_web_import.py test_ui_samples)이 실제 /api/devices 와 대조하는 같은 견본을 Devices 타입에 묶는다.
import { expect, test } from "vitest";
import type { Devices } from "./devApi";
import sample from "./devices.sample.json";

const typed = sample satisfies Devices;

test("견본 = 장치 한 대 · 선택지", () => {
  expect(typed.devices[0].policy.actions.length).toBeGreaterThan(0);
  expect(typed.choices.token_days).toBeGreaterThan(0);
});
