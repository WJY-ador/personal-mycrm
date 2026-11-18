// 항목 필드 값(참조 필드 제외) — 정의의 필드 이름 · 값(선택지 이름 · 날짜 · 목록 · 예/아니오). AI 필드(ai_*)는 「AI 요약」 표시(사용자의 말이 아니다)
import { dOnly } from "../../shared/date";
import type { Field, Item } from "../../shared/state";
import { AI_MARK } from "../../shared/words";
import { defById, type World } from "./model";

// 값 한 칸의 글자 — 목록 보기 열과 항목 페이지가 같이 쓴다. 빈 값 = ""
export function fieldText(f: Pick<Field, "value_type" | "options">, v: unknown): string {
  if (v == null || v === "" || (Array.isArray(v) && !v.length)) return "";
  const o = f.value_type === "select" ? (f.options || []).find(x => x.value === v) : null;
  return o ? o.label : f.value_type === "date" ? dOnly(String(v)) || String(v) : Array.isArray(v) ? v.join(", ") : typeof v === "boolean" ? (v ? "예" : "아니오") : String(v);
}
export const isAiField = (key: string) => key.startsWith("ai_");

export function FieldRows({ W, it }: { W: World; it: Item }) {
  const rows = (defById(W, it.object_id)?.fields || []).filter(f => f.value_type !== "reference").flatMap(f => {
    const s = fieldText(f, (it.data || {})[f.key]);
    if (!s) return [];
    return [<dt key={`t${f.key}`}>{f.label}{isAiField(f.key) && <> <span className="chip o-ai">{AI_MARK}</span></>}</dt>, <dd key={`d${f.key}`}>{s}</dd>];
  });
  return rows.length ? <dl className="kv">{rows}</dl> : null;
}
