// 축 잇기(2026-11-18 명세 4절) 서버 접점 — 축 보기(GET /api/axes) · 축 한 장(GET /api/axes?id=<축 item id> 의 page.body) · 수집 글 목록의 축 필터 쿼리 꼴.
// 「나」 축 탭과 오늘 탭 「오늘의 축」이 같이 쓴다(features 끼리 import 금지라 여기 한 벌). 응답 모양 정본 = server/imports.py axis_overview. 견본 = axes.sample.json.
import { useQuery } from "@tanstack/react-query";
import { getJSON } from "./api";

// 화면이 쓰는 꼴(AxisSum·AxisPage). 서버 응답 꼴(Raw*)은 아래 axesApi 한 곳에서만 바꾼다 — 서버 꼴이 바뀌면 여기만 고친다.
export type AxisSum = {
  item_id: string; code: string | null; title: string; body: string; keywords: string[];
  pending: number; kept: number; total: number; page: { record_id: string; updated_at: string } | null;
};
export type AxesOverview = { axes: AxisSum[] };
export type AxisPage = { record_id: string; updated_at: string; markdown: string };
// 서버 응답(GET /api/axes[?id=], imports.axis_overview — MCP axis_overview_get 과 같은 함수). id 를 주면 그 축 하나 + page.body(markdown)
type RawPage = { record_id: string; title: string | null; at: string | null; ai: boolean; notice: string; body?: string };
export type RawAxis = { id: string; code: string | null; title: string | null; keywords: string[]; description: string;
  counts: { pending: number; kept: number; total: number }; page: RawPage | null };
export type RawAxes = { ready: boolean; axes: RawAxis[] };

const enc = encodeURIComponent;
export const AXES_QK = ["axes", "overview"] as const;
const sum = (a: RawAxis): AxisSum => ({ item_id: a.id, code: a.code, title: a.title || "", body: a.description || "", keywords: a.keywords || [],
  pending: a.counts?.pending || 0, kept: a.counts?.kept || 0, total: a.counts?.total || 0,
  page: a.page ? { record_id: a.page.record_id, updated_at: a.page.at || "" } : null });
export const axesApi = {
  overview: async (): Promise<AxesOverview> => ({ axes: ((await getJSON<RawAxes>("/api/axes")).axes || []).map(sum) }),
  // 한 장 = 그 축의 최신 한 장 기록 본문. 없으면 null(실패 아님)
  page: async (itemId: string): Promise<AxisPage | null> => {
    const p = (await getJSON<RawAxes>(`/api/axes?id=${enc(itemId)}`)).axes?.[0]?.page;
    return p && typeof p.body === "string" ? { record_id: p.record_id, updated_at: p.at || "", markdown: p.body } : null;
  },
};
// 수집 글 목록 보기(GET /api/me/objects/<key>)의 축 필터 — 쿼리 꼴은 이 한 줄에만 둔다
export const axisParam = (itemId: string): [string, string] => ["f.axes", itemId];
export const useAxes = () => useQuery({ queryKey: AXES_QK, queryFn: axesApi.overview });
export const COLLECTED_KEY = "collected_posts";   // 수집 글 오브젝트 key(서버 imports.COLLECTED_OBJECT_KEY)
export const axisHref = (itemId: string) => `#_me/axis/${enc(itemId)}`;

// 축 색 = 축 순서 1~8, 9번째부터 회색(건수와 무관하게 고정 — 대기 0 을 숨겨도 색이 밀리지 않게 전체 순서의 번호를 쓴다)
export const AX_COLORS = 8;
export const axColor = (i: number) => (i < AX_COLORS ? `var(--ax${i + 1})` : "var(--soft)");

// 행의 축({id, code, title}) → 코드 칩 값. 코드가 비면 by(축 보기, 축 항목)의 코드, 그래도 없으면 이름, 그것도 없으면 뺀다
export type AxisRef = { id: string; code?: string | null; title?: string | null };
export function axisCodes(refs: AxisRef[] | null | undefined, by: Record<string, { code: string | null; title: string }>) {
  return (refs || []).map(r => {
    const k = by[r.id];
    return { id: r.id, code: r.code || k?.code || r.title || k?.title || "", title: r.title || k?.title || "" };
  }).filter(r => r.code);
}
export const axisMap = (axes: AxisSum[] | undefined) => Object.fromEntries((axes || []).map(a => [a.item_id, { code: a.code, title: a.title }]));
