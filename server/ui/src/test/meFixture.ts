// 시험 도우미 — 「나」 화면용 가짜 상태 S·통계·레이아웃·기록 본문 + 미디어 질의(jsdom 에 없다). 화면 코드가 아니다(*.test 만 import).
import { vi } from "vitest";

const T = (d: string) => `2026-${d}T01:00:00+00:00`;
const item = (id: string, object_id: string, title: string, o: object = {}) => ({ id, object_id, code: null, title, body: "", data: {}, decision: null,
  revision: 1, semantic_kind: "collection", proposal: null, links: [], created_at: T("10-01"), updated_at: T("10-01"), ...o });

export function meState(o: object = {}) {
  return {
    user: { display_name: "홍길동", nav: "new" }, switches: { trash: true },
    journal: [{ id: "r1", title: "도입 메모", excerpt: "도입 회의", created: T("11-01"), source: null, source_id: "s1", question_id: "q1", source_date: null, author_kind: "self" }],
    journal_next_before: null,
    questions: [{ id: "q1", text: "순서는?", created: T("10-02") }],
    candidates: [{ id: "c1", text: "담당 먼저", status: "pending", record_id: "r1", question_id: "q1", quote: "입력 **담당**", review: null, revision: 1, created: T("11-02") }],
    items: [
      item("p1", "od_p", "담당이 먼저", { code: "P-1", body: "본문 **굵게**", decision: "pending", revision: 2, semantic_kind: "principle",
        links: [{ field_key: "claims", target_kind: "candidate", target_id: "c1" }] }),
      item("p2", "od_p", "두 번째 기준", { decision: "confirmed", semantic_kind: "principle" }),
      item("a1", "od_ax", "고객 이해"), item("a2", "od_ax", "실행 속도"),
    ],
    item_proposals: [],
    definitions: [
      { id: "od_p", key: "principles", label: "기준", std_id: "std:principles", archived_at: null, fields: [] },
      { id: "od_e", key: "events", label: "결정", std_id: "std:decision_events", archived_at: null, fields: [] },
      { id: "od_ax", key: "axes", label: "축", std_id: "std:axes", archived_at: null, fields: [] },
    ],
    record_links: [{ record_id: "r1", field_key: "axes", target_kind: "item", target_id: "a1" }],
    people: [{ id: "pe1", alias: "민수", revision: 1, created: T("10-03") }],
    reflections: [{ id: "f1", source_id: "s1", kind: "summary", body: "읽고 든 생각\n둘째 줄", review: "pending", revision: 2, created: T("10-04"), updated: T("10-04") }],
    sources: [{ id: "s1", kind: "url", name: "블로그", location: null }],
    source_counts: { by_source: { s1: 1 }, unconfirmed: 0 },
    activity_ui: { actions: { like: "좋아요" } },
    ...o,
  };
}

export const STATS = {
  axes: [{ id: "a1", code: null, title: "고객 이해", items: 0, records: 1, readings: 0, n: 1 }, { id: "a2", code: null, title: "실행 속도", items: 0, records: 0, readings: 0, n: 0 }],
  heatmap: { from: "2026-08-10", to: "2026-11-08", cells: Array.from({ length: 91 }, (_, i) => ({ d: new Date(Date.UTC(2026, 7, 10 + i)).toISOString().slice(0, 10), records: i === 80 ? 2 : 0, activities: 0 })) },
  kinds: { principle: 2, decision: 0, axis: 2, custom: 0, records: 1, readings: 0, people: 1, sources: 1 },
  waiting: { candidates_pending: 1, principles_pending: 1, inbox_pending: 0 },
};
export const TABS = ["summary", "principle", "decision", "axis", "custom", "person", "source"];
export const layout = (tabs = TABS, summary = ["heatmap", "kinds", "waiting", "recent"]) =>
  ({ layout: { v: 2, pages: { me: { tabs, regions: { summary: summary.map(c => ({ c, p: {} })) } } } }, version: 3 });
export const JOURNAL = { id: "r1", title: "도입 메모", body: "# 도입 메모\n\n도입 회의에서 입력 **담당**을 먼저 정했다.\n\n둘째 문단", revision: 4, author_kind: "self",
  meta: { created: T("11-01"), source: null, question_id: "q1" } };

export function installMedia(narrow = false) {
  vi.stubGlobal("matchMedia", (q: string) => ({ matches: narrow && q.includes("767"), media: q, addEventListener() {}, removeEventListener() {} }));
}
