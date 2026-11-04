// 세션 정리 A안(2026-11-04) — 「내 결정」 표시(records.decision_owner)는 화면 어디에도 보이지 않는다(원작자).
// 서버는 이 값을 /app 응답에 싣지 않는다(server/test_session_wrap.py). 혹시 실려 와도 내 글 상세·목록 DOM 에 값·문구가 없어야 한다.
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { queryClient } from "../../shared/queries";
import { calls, installFetch, json, serve } from "../../test/fakeServer";
import { installMedia, JOURNAL, meState } from "../../test/meFixture";
import { hideMe, showMe } from "../../test/showMe";

const OWNED = { ...JOURNAL, text_process: "structured", source: "세션 정리", decision_owner: "self" };
const LEAK = ["decision_owner", "내 결정", "결정은 본인"];

beforeEach(() => {
  installFetch();
  installMedia(false);
  queryClient.clear();
  serve(url => (url.startsWith("/api/journal?id=r1") ? json(200, OWNED)
    : url.startsWith("/api/axes/") ? json(200, { activities: [], activity_count: 0 }) : json(404, { code: "NOT-FOUND", msg: "" })));
});
afterEach(() => { hideMe(); vi.unstubAllGlobals(); });

test("「내 결정」 표시가 실려 와도 내 글 상세(목록 행 포함 상태)에 값·문구·속성 0", async () => {
  const S = meState();
  const el = await showMe("#_me/journal/r1", { ...S, journal: (S.journal || []).map(r => ({ ...r, decision_owner: "self" })) });
  expect(calls.some(c => c.url === "/api/journal?id=r1")).toBe(true);
  const html = new XMLSerializer().serializeToString(el);   // 글자·속성(툴팁 title 포함) 전부
  for (const w of LEAK) expect(html).not.toContain(w);
  expect(el.querySelector("#home-detail")!.textContent).toContain("도입 회의에서 입력 담당을 먼저 정했다.");
});
