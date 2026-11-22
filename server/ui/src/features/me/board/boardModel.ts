// 한판 상세 계산(순수) — 출처 카드 기호(들어온 것 a, b… 에 이어 내가 정한 것) · 소제목마다 나온 곳 기호 · 선 목록(소제목 × 출처).
// 선은 데이터에서 정한다(위치는 BoardLinks 가 화면에서 잰다) — 시험은 이 목록과 강조 상태만 본다.
import type { RoutineDetail, RoutineRef } from "../meApi";

export const refKey = (r: Pick<RoutineRef, "kind" | "id">) => `${r.kind}:${r.id}`;
const sym = (i: number) => (i < 26 ? String.fromCharCode(97 + i) : `z${i - 25}`);
export type Link = { o: number; k: string };   // o = 소제목 순번(0부터) · k = 출처 기호

export function boardModel(d: RoutineDetail) {
  const syms: Record<string, string> = {};
  let n = 0;
  for (const r of [...d.inflow, ...d.decided]) if (!syms[refKey(r)]) syms[refKey(r)] = sym(n++);
  const from = d.subheads.map(s => [...new Set(s.sources.map(r => syms[refKey(r)]).filter(Boolean))]);
  const links: Link[] = from.flatMap((ks, o) => ks.map(k => ({ o, k })));
  return { syms, from, links };
}
