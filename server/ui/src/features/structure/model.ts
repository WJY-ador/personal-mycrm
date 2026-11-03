// 구조 화면이 상태(S)에서 읽는 것 — 옛 defById·objLabel·eventLabel·promoOf·linkCount·incomingCounts·fieldVal·dataSummary 와 같은 규칙. 문구는 글자 그대로.
import type { AppState, Def, Field, Item } from "../../shared/state";

export const FILTERS: [string, string][] = [["confirmed", "확정한 판단"], ["pending", "아직 안 정함"], ["excluded", "반영 안 함"], ["all", "전부"]];
export const STCHIP: Record<string, [string, string]> = { confirmed: ["st-mine", "확정한 판단"], pending: ["st-wait", "아직 안 정함"], excluded: ["st-off", "반영 안 함"] };
export const NOCARD: Record<string, string> = { confirmed: "아직 확정한 판단이 없어요. 검토할 판단을 원문과 대조해 남기면 여기에 쌓여요.",
  pending: "정할 문장이 남아 있지 않아요.", excluded: "반영 안 함으로 둔 문장이 없어요.", all: "아직 뽑힌 문장이 없어요. 내 글에서 판단을 뽑으면 여기에 떠요." };
export const ITEM_SAVED: Record<string, string> = { apply: "적용했어요.", confirm: "남겼어요.", exclude: "반영 안 함으로 표시했어요.", pending: "아직 안 정함으로 돌렸어요.",
  discard: "제안을 제외했어요." };
export const HIST_LABEL: Record<string, string> = { apply: "적용", confirm: "남김", exclude: "반영 안 함", pending: "아직 안 정함", archive: "보관", restore: "되돌림" };
export const CONFLICT_TEXT = "다른 곳에서 먼저 바뀌었어요. 새로 고침해 다시 봐 주세요.";
export const TAB = "structure";   // 옛 BASE.structure — 대조 경로·카드 주소의 탭 id

export const defById = (S: AppState, id: string) => (S.definitions || []).find(d => d.id === id);
export const objLabel = (S: AppState, id: string) => defById(S, id)?.label || "항목";
export const promoOf = (d: Def | undefined) => d?.policy?.promotion || null;
// 기준 정의의 결정(event) 필드가 가리키는 오브젝트 라벨 — 원작자 템플릿이면 「결정」
export function eventLabel(S: AppState, d: Def | undefined) {
  const p = promoOf(d), f = p && (d!.fields || []).find(x => x.key === p.event_field);
  return f && f.target_object_id && defById(S, f.target_object_id) ? objLabel(S, f.target_object_id) : "결정";
}
export const linkCount = (it: Pick<Item, "links">, key?: string) => (key ? (it.links || []).filter(l => l.field_key === key).length : 0);
// 들어오는 관계(다른 항목이 이 항목을 가리킴)를 오브젝트 라벨별로
export function incomingCounts(S: AppState, id: string) {
  const out: Record<string, number> = {};
  for (const it of S.items || []) for (const l of it.links || [])
    if (l.target_kind === "item" && l.target_id === id) { const lb = objLabel(S, it.object_id); out[lb] = (out[lb] || 0) + 1; }
  return out;
}
export function fieldVal(f: Field, v: unknown): string {
  if (v == null || v === "" || (Array.isArray(v) && !v.length)) return "";
  if (f.value_type === "select") { const o = (f.options || []).find(x => x.value === v); return o ? o.label : String(v); }
  if (f.value_type === "boolean") return v ? "예" : "아니오";
  return Array.isArray(v) ? v.join(", ") : String(v);
}
export const dataSummary = (it: Pick<Item, "data">, d: Def | undefined) => ((d && d.fields) || []).filter(f => !["reference", "select"].includes(f.value_type)).map(f => {
  const v = (it.data || {})[f.key];
  if (v == null || v === "" || (Array.isArray(v) && !v.length)) return "";
  return `${f.label} ${Array.isArray(v) ? v.join(", ") : v}`;
}).filter(Boolean).join(" · ");
// 적용 전 새 항목(revision 0)은 제안 값으로 보인다
export const viewOf = (it: Item): Item => (it.revision ? it : { ...it, title: it.proposal?.title ?? null, body: it.proposal?.body ?? null,
  data: it.proposal?.data || {}, links: it.proposal?.links || [], code: it.proposal?.code ?? null });
