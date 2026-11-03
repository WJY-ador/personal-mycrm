// 항목 필드 값(참조 필드 제외) — 정의의 필드 이름 · 값(선택지 이름 · 날짜 · 목록 · 예/아니오)
import { dOnly } from "../../shared/date";
import type { Item } from "../../shared/state";
import { defById, type World } from "./model";

export function FieldRows({ W, it }: { W: World; it: Item }) {
  const rows = (defById(W, it.object_id)?.fields || []).filter(f => f.value_type !== "reference").flatMap(f => {
    const v = (it.data || {})[f.key];
    if (v == null || v === "" || (Array.isArray(v) && !v.length)) return [];
    const o = f.value_type === "select" ? (f.options || []).find(x => x.value === v) : null;
    const s = o ? o.label : f.value_type === "date" ? dOnly(String(v)) || String(v) : Array.isArray(v) ? v.join(", ") : typeof v === "boolean" ? (v ? "예" : "아니오") : String(v);
    return [<dt key={`t${f.key}`}>{f.label}</dt>, <dd key={`d${f.key}`}>{s}</dd>];
  });
  return rows.length ? <dl className="kv">{rows}</dl> : null;
}
