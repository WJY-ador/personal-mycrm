// 구조 추천 칸 서버 접점(2026-11-18 구조추천 명세 6.5) — 읽기 GET /api/structure/reco(초안 카드), 쓰기 POST /api/structure/drafts/{apply|rename|discard}.
// 응답 모양 정본 = server/web.py structure_reco(건수, 견본 = route.profile drafts). 견본 대조 = reco.sample.json ↔ server/test_route_screen.py.
import { getJSON, postJSON } from "../../shared/api";

export type RecoField = { key: string; label: string; value_type: string; from: string };
export type RecoSample = { record_id: string; unit_key: string; title: string; quote: string };
export type RecoDraft = {
  object_id: string; proposal_id: string; base_revision: number; key: string; label: string; semantic_kind: string | null;
  fields: RecoField[]; has_route: boolean; rule: string; would_fill: number; partial: number; samples: RecoSample[];
};
export type Reco = { drafts: RecoDraft[]; suggest: boolean; unattached: number; ask: string };
export const RECO_KEY = ["structure", "reco"];
const ids = (d: RecoDraft) => ({ object_id: d.object_id, proposal_id: d.proposal_id });
export const recoApi = {
  get: () => getJSON<Reco>("/api/structure/reco"),
  apply: (d: RecoDraft) => postJSON("/api/structure/drafts/apply", { ...ids(d), expected_revision: d.base_revision }),
  rename: (d: RecoDraft, label: string) => postJSON("/api/structure/drafts/rename", { ...ids(d), expected_revision: d.base_revision, label }),
  discard: (d: RecoDraft) => postJSON("/api/structure/drafts/discard", ids(d)),
};
