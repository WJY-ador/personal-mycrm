// API 견본 대조(TS 쪽) — 서버 시험(test_web_home.py test_ui_samples)이 실제 /api/feedback·/api/feedback/<id> 와 대조하는 같은 견본을 문의 타입에 묶는다.
import { expect, test } from "vitest";
import type { Ticket, TicketOne } from "./deskApi";
import sample from "./desk.sample.json";

const list = sample.list satisfies { tickets: Ticket[] };
const one = sample.one satisfies TicketOne;

test("견본 = 내 문의 하나 · 상세(답변·공개 이력)", () => {
  expect(list.tickets[0].has_reply).toBe(true);
  expect(one.history[0].kind).toBe("status");
});
