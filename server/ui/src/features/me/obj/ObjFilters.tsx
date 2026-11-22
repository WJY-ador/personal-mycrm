// 목록 머리의 「걸린 필터」 칩 한 줄(2026-11-22 구현계획 1절) — 최근 N일 · 판정 · 축 · 상태 · 선택 칸 값. 칩을 누르면 그 필터만 풀린다(따로 버튼 없음).
// 주소에 남은 필터 쿼리(?window=7…)는 ObjTab 의 setVq 가 뗀다(새로 고침해도 풀린 그대로).
import type { Def } from "../../../shared/state";
import type { ObjList, ObjQuery } from "../meApi";
import { axes, type World } from "../model";
import { OBJ_STATE, OBJ_TEXT } from "../text";
import css from "./Obj.module.css";

export const VERDICT_LABEL: Record<string, string> = { right: "맞았다", unknown: "미확인", partial: "일부", wrong: "틀렸다", none: "판정 없음" };
type Chip = { key: string; text: string; off: (q: ObjQuery) => ObjQuery };

const fieldLabel = (def: Def, k: string) => def.fields.find(f => f.key === k)?.label || k;

export function filterChips(W: World, def: Def, vq: ObjQuery, first: ObjList | undefined): Chip[] {
  const out: Chip[] = [];
  if (vq.window) out.push({ key: "window", text: OBJ_TEXT.window(vq.window), off: q => ({ ...q, window: undefined }) });
  if (vq.verdict) {
    const i = vq.verdict.lastIndexOf(":"), f = vq.verdict.slice(0, i), c = vq.verdict.slice(i + 1);
    out.push({ key: "verdict", text: `${fieldLabel(def, f)}: ${VERDICT_LABEL[c] || c}`, off: q => ({ ...q, verdict: undefined }) });
  }
  if (vq.axis) {
    const a = axes(W).find(x => x.id === vq.axis);
    out.push({ key: "axis", text: `${OBJ_TEXT.axis}: ${a?.code || a?.title || "?"}`, off: q => ({ ...q, axis: undefined }) });
  }
  if (vq.state) out.push({ key: "state", text: `${OBJ_TEXT.state}: ${OBJ_STATE.find(s => s[0] === vq.state)?.[1] || vq.state}`, off: q => ({ ...q, state: "" }) });
  for (const [k, v] of Object.entries(vq.f)) {
    if (!v) continue;
    const fl = first?.filters.find(x => x.key === k);
    const vl = fl?.values.find(x => x.value === v)?.label || def.fields.find(f => f.key === k)?.options?.find(o => o.value === v)?.label || v;
    out.push({ key: "f." + k, text: `${fl?.label || fieldLabel(def, k)}: ${vl}`, off: q => ({ ...q, f: { ...q.f, [k]: "" } }) });
  }
  return out;
}

// hide = 그 화면이 고정한 필터(축 화면의 축) — 칩으로 보이지 않는다
export function ObjFilters({ W, def, vq, setVq, first, hide = [] }: { W: World; def: Def; vq: ObjQuery; setVq: (q: ObjQuery) => void; first: ObjList | undefined; hide?: string[] }) {
  const chips = filterChips(W, def, vq, first).filter(c => !hide.includes(c.key));
  if (!chips.length) return null;
  const off = (c: Chip) => setVq(c.off(vq));   // 주소 쿼리 떼기는 setVq(ObjTab)가 한다
  return (
    <div className={css.on} role="group" aria-label={OBJ_TEXT.on} id="obj-filters">
      {chips.map(c => <button key={c.key} type="button" className={`chip ${css.chip}`} aria-pressed="true" title={OBJ_TEXT.off}
        aria-label={`${c.text}, ${OBJ_TEXT.off}`} onClick={() => off(c)}>{c.text}<span className={css.x} aria-hidden="true">×</span></button>)}
    </div>
  );
}
