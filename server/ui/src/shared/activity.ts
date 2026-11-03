// 활동 한 줄의 모양(손 사본) — 서버 정본 = server/activity.py(activity_list·activity_get·문맥 API 의 activities).
// 「나」(사람·축·출처 문맥)·활동 화면이 같이 쓴다. 견본 대조 = features/activity/activity.sample.json ↔ server/test_web_import.py.
export type Act = {
  id: string; action: string; action_label?: string; occurred_on: string | null; observed_on?: string | null; state?: string;
  received_at?: string; source?: { id: string; name: string; provider?: string | null } | null;
  people?: { id: string; alias: string; role?: string }[]; axes?: { id: string; title: string | null }[]; memo_count?: number;
};

export const ROLE_LABEL: Record<string, string> = { author: "글쓴이", counterparty: "상대", participant: "참여자" };

// 행동 이름 — 서버 상수(/api/state activity_ui.actions) 그대로, 모르면 코드
export const actLabel = (actions: Record<string, string> | undefined, a: string) => actions?.[a] || a;

// 활동 현황(서버 activity.me_aggregate 그대로 — 화면이 다시 세지 않는다). /api/state activity(30일) · /api/me/aggregate?period=
export type Agg = {
  period: string; from: string | null; to: string; total: number; notice: string;
  by_action: { action: string; label: string; n: number }[];
  by_axis: { item_id: string; title: string | null; n: number }[];
  axis_unclassified: number; axis_sum_differs: boolean;
  top_people: { person_id: string; alias: string; n: number }[];
  by_source: { source_id: string; name: string; provider: string | null; n: number }[];
  undated: { n: number; observed: { observed_on: string | null; n: number }[] };
  grounds: { principles: { item_id: string; title: string | null; records: number; activities: number }[] };
};
