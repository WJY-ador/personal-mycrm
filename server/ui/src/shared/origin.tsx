// 구조 정의 출처 칩 — 정본 = 서버 structure_svg.ORIGIN_TEXT·ORIGIN_CATEGORY(/api/state origin_labels). 화면은 사본을 두지 않는다.
// 범주 standard = 「o-std」, 그 밖 = 「o-tpl」(옛 app.html originChip 그대로). 값이 없으면(옛 서버) 출처 코드 글자 그대로.
import type { AppState } from "./state";

export function originChip(S: AppState, o: string): [string, string] {
  const L = S.origin_labels;
  const text = L?.text[o] ?? o, cat = L?.category[o];
  return [o !== "custom" && cat === "standard" ? "o-std" : cat ? "o-tpl" : "", text];
}

// 그래프 범례 — 범주 이름(standard·template …) 하나씩, 응답 순서 그대로
export const originCategories = (S: AppState) => [...new Set(Object.values(S.origin_labels?.category || {}))];

export function OriginChip({ S, o }: { S: AppState; o: string }) {
  const [c, t] = originChip(S, o);
  return <span className={`chip ${c}`.trim()}>{t}</span>;
}
