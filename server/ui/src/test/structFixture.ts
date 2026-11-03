// 시험 도우미 — 질문·기록·구조·내 구조 설정·지도·마스트용 가짜 상태(S)·항목 하나·편입 미리보기. 화면 코드가 아니다(*.test 만 import). 이름·내용은 가짜.
const T = (d: string) => `2026-${d}T01:00:00+00:00`;
const cand = (id: string, status: string, o: object = {}) => ({ id, text: `판단 ${id}`, status, record_id: "r1", question_id: "q1", quote: "입력 **담당**",
  review: null, revision: 1, created: T("11-02"), origin: "ai", edited_by_user: false, wording_by: null, wording_approved: true, ...o });
export const ORIGIN_LABELS = { text: { core: "표준", standard: "표준", template: "커스텀", custom: "커스텀" },
  category: { core: "standard", standard: "standard", template: "template", custom: "template" } };
export const SVG = '<svg class="dmo-svg" viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="구조 그래프"><title>구조 그래프</title>'
  + '<script>alert(1)</script><a href="#dmo-o1" aria-label="기준"><title>기준</title><circle cx="50" cy="50" r="42" style="fill:var(--dmo-standard-bg);stroke:red" stroke-width="1.6" onclick="x()"/>'
  + '<text x="50" y="50" font-size="12.5" text-anchor="middle">기준</text></a><a href="javascript:alert(1)"><text>나쁜 링크</text></a>'
  + '<a href="#dmo-r1"><line x1="1" y1="1" x2="2" y2="2"/></a></svg>';

export function structState(o: object = {}) {
  return {
    user: { display_name: "홍길동", nav: "new", email: "hong@example.com", struct_names: false }, switches: { trash: false },
    journal: [{ id: "r1", title: "도입 메모", excerpt: "도입 회의", created: T("11-01"), source: null, source_id: "s1", question_id: "q1", source_date: null, author_kind: "self", ingest_kind: null },
      { id: "r2", title: "회고", excerpt: "회고 메모", created: T("10-20"), source: "파일:x.md", source_id: null, question_id: null, source_date: null, author_kind: "self", ingest_kind: null }],
    journal_next_before: null,
    questions: [{ id: "q1", text: "도구보다 담당이 먼저인가?", created: T("10-02") }, { id: "q2", text: "두 번째 질문", created: T("10-03") }],
    candidates: [cand("c1", "confirmed"), cand("c2", "pending"), cand("c3", "excluded", { origin: "memo", edited_by_user: true }), cand("c4", "pending", { question_id: null, record_id: "r2", wording_by: "ai", wording_approved: false })],
    items: [{ id: "p1", object_id: "od_p", code: "P-1", title: "담당이 먼저", body: "본문 **굵게**", data: {}, decision: "pending", revision: 2, semantic_kind: "principle",
      proposal: null, links: [{ field_key: "claims", target_kind: "candidate", target_id: "c1" }], created_at: T("10-01"), updated_at: T("10-05"), promotion: { met: true, confirmed_claims: 1, confirmed_claims_min: 1 } },
      { id: "p2", object_id: "od_p", code: null, title: "확정 기준", body: "", data: {}, decision: "confirmed", revision: 3, semantic_kind: "principle",
        proposal: null, links: [], created_at: T("10-01"), updated_at: T("10-06") },
      { id: "a1", object_id: "od_ax", code: null, title: "고객 이해", body: "", data: { keywords: ["고객"] }, decision: null, revision: 1, semantic_kind: "collection",
        proposal: null, links: [], created_at: T("10-01"), updated_at: T("10-04") }],
    item_proposals: [{ id: "n1", object_id: "od_p", code: null, title: null, body: null, data: null, decision: null, revision: 0, semantic_kind: "principle",
      proposal: { proposal_id: "pr_n1", title: "새 기준 제안", body: "제안 본문", code: "P-2", data: {}, links: [] }, links: [], created_at: T("10-07"), updated_at: T("10-07") }],
    definitions: [
      { id: "od_p", key: "principles", label: "기준", semantic_kind: "principle", std_id: "std:principles", archived_at: null,
        fields: [{ key: "claims", label: "근거", value_type: "reference", options: [] }], policy: { promotion: { claim_field: "claims" } } },
      { id: "od_ax", key: "axes", label: "축", semantic_kind: "collection", std_id: "std:axes", archived_at: null,
        fields: [{ key: "keywords", label: "검색어", value_type: "text_list", options: [] }] },
    ],
    record_links: [{ record_id: "r1", field_key: "axes", target_kind: "item", target_id: "a1" }],
    people: [], reflections: [],
    sources: [{ id: "s1", kind: "url", name: "블로그", location: "https://example.com" }],
    source_counts: { by_source: { s1: 1 }, unconfirmed: 1 },
    activity_ui: { actions: {}, providers: {}, pending_days: 7 },
    tabs: [], me: { counts: {} },
    next: { kind: "record", text: "기록 1편을 남겨 보세요." },
    structure: { objects: [
      { id: "od_p", key: "principles", label: "기준", origin: "standard", semantic_kind: "principle", locked: true, std_name: "기준",
        fields: [{ key: "claims", label: "근거", value_type: "reference", origin: "standard", locked: true, std_name: "근거" }] },
      { id: "od_x", key: "homework", label: "숙제", origin: "custom", semantic_kind: "collection", locked: false, std_name: null,
        fields: [{ key: "due", label: "기한", value_type: "date", origin: "custom", locked: false, std_name: null }] }],
      relations: [{ object_id: "od_p", field_key: "claims", target_kind: "candidate", target_object_id: null, cardinality: "N:N", origin: "standard", locked: true }],
      core: [{ kind: "candidate", origin: "core" }] },
    structure_svg: SVG, origin_labels: ORIGIN_LABELS,
    ...o,
  };
}

export const ITEM = { id: "p1", object_id: "od_p", code: "P-1", title: "담당이 먼저", body: "본문 **굵게**", data: {}, decision: "pending", revision: 2, semantic_kind: "principle",
  proposal: { proposal_id: "pr1", title: "담당이 가장 먼저", body: "본문 **굵게**", data: {}, links: [{ field_key: "claims", target_kind: "candidate", target_id: "c1" }, { field_key: "claims", target_kind: "candidate", target_id: "c9" }], proposed_at: T("10-08") },
  links: [{ field_key: "claims", target_kind: "candidate", target_id: "c1" }, { field_key: "claims", target_kind: "candidate", target_id: "c9" }],
  created_at: T("10-01"), updated_at: T("10-05"), promotion: { met: true, confirmed_claims: 1, confirmed_claims_min: 1 },
  object: { id: "od_p", key: "principles", label: "기준", semantic_kind: "principle", revision: 1 },
  fields: [{ key: "claims", label: "근거", value_type: "reference", options: [], target_kind: "candidate" }],
  targets: [{ target_kind: "candidate", target_id: "c1", target: { id: "c1", text: "판단 c1", status: "confirmed", record_id: "r1", quote: "입력 **담당**" } },
    { target_kind: "candidate", target_id: "c9", target: null }],
  incoming: [{ field_key: "rules", source_item_id: "e1", source_record_id: null, code: "D-1", title: "결정 하나", object_id: "od_e", object_label: "결정", record_title: null }],
  history: [{ id: 1, action: "apply", prev_revision: 0, at: T("10-01") }, { id: 2, action: "confirm", prev_revision: 1, at: T("10-02") }],
};

export const PREVIEW = { version: "1", std: {}, objects: [
  { std_key: "principles", std_name: "기준", state: "seeded", structure: "match", object: { id: "od_p", key: "principles", label: "기준", revision: 1, archived: false },
    conflicts: [], meaning_check: true, needs: [], lock: { changes: ["archive", "key"], fields: ["claims"] }, can_incorporate: false, blocked: ["already"] },
  { std_key: "axes", std_name: "축", state: "none", structure: "extend", object: { id: "od_ax", key: "axes", label: "축", revision: 4, archived: false },
    conflicts: [], meaning_check: true, needs: [], lock: { changes: ["archive", "field_remove"], fields: ["keywords"] }, can_incorporate: true, blocked: [] },
  { std_key: "decision_events", std_name: "결정", state: "deferred", structure: "conflict", object: null,
    conflicts: [{ code: "field_missing", field: "rules" }], meaning_check: false, needs: [{ field: "rules", std_key: "principles", state: "seeded", ready: true }],
    lock: { changes: [], fields: [] }, can_incorporate: false, blocked: ["conflict"] }] };

export const JOURNAL = { id: "r1", title: "도입 메모", body: "# 도입 메모\n\n도입 회의에서 입력 **담당**을 먼저 정했다.\n\n둘째 문단", revision: 4, author_kind: "self",
  meta: { created: T("11-01"), source: null, question_id: "q1" } };
