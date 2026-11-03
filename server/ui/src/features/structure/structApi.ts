// 구조 서랍 서버 접점 — 항목 하나(/api/item: 항목 + 정의 요약 + 필드 + 관계 대상 + 들어오는 관계 + 이력 + 승격). 응답 정본 = server/db.py item_get.
// 견본 대조 = item.sample.json ↔ server/test_web_home.py test_ui_samples(키 집합까지). 쓰기 = shared/item.ts(결정·휴지통).
import { getJSON } from "../../shared/api";
import type { Field, Item } from "../../shared/state";

export type Target = { target_kind: string; target_id: string; target: Record<string, unknown> | null };
export type Incoming = { field_key: string; source_item_id: string | null; source_record_id: string | null; code: string | null; title: string | null;
  object_id: string | null; object_label: string | null; record_title: string | null };
export type Hist = { id: number; action: string; prev_revision: number; at: string };
export type ItemFull = Item & {
  object: { id: string; key: string; label: string; semantic_kind: string; revision: number };
  fields: (Field & { target_kind?: string | null })[]; targets: Target[]; incoming: Incoming[]; history: Hist[];
};
export const itemKey = (id: string) => ["item", id];
export const fetchItem = (id: string) => getJSON<ItemFull>("/api/item?id=" + encodeURIComponent(id));
