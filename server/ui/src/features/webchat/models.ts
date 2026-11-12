// 모델 목록 나누기(대화 하나로 J-F5) — PC 마다, 공급자마다 계열별 가장 새 판 하나씩 위에 두고 나머지는 "다른 모델"로 접는다.
// 무엇이 최신인지는 PC 가 알려 준 목록 안에서 이름 규칙으로만 고른다. 목록에 없는 모델을 만들지 않는다(결정 4).
// 이름 규칙: - . _ 로 나눈 조각 중 숫자 = 판(8자리 이상 = 날짜 꼬리표, 판으로 세지 않는다), 나머지 = 계열. 공급자 이름 조각(claude 등)은 계열에서 뺀다.
//   claude-opus-5-5 → 계열 opus, 판 5.5, claude-opus-5 → opus, 5, gpt-5.6-sol → gpt-sol, 5.6
// 판이 없는 이름(opus 같은 별칭), 계열 글자가 없는 이름, 기본 모델(null)은 규칙이 못 읽으니 접지 않고 위에 둔다.
import type { Choice } from "./store";

const key = (c: Choice) => `${c.device}|${c.provider}|${c.model ?? ""}`;   // store 의 선택 키와 같은 꼴(순환 import 를 피한다)

type Parsed = { family: string; version: number[]; date: number };

export function parseModel(provider: string, model: string | null): Parsed | null {
  if (!model) return null;
  const words: string[] = [], version: number[] = [];
  let date = 0;
  for (const part of model.toLowerCase().split(/[-._]/)) {
    if (!part) continue;
    if (/^\d+$/.test(part)) { if (part.length >= 8) date = Number(part); else version.push(Number(part)); }
    else if (part !== provider) words.push(part);
  }
  return version.length && words.length ? { family: words.join("-"), version, date } : null;
}

// 판이 높은 쪽. 같은 계열, 같은 판이면 날짜 꼬리표가 없는 이름(별칭 꼴)을 위에, 둘 다 있으면 늦은 날짜를(2026-11-12 메인)
function newer(a: Parsed, b: Parsed) {
  for (let i = 0; i < Math.max(a.version.length, b.version.length); i++) {
    const x = a.version[i] ?? -1, y = b.version[i] ?? -1;
    if (x !== y) return x > y;
  }
  if (!a.date || !b.date) return !a.date && !!b.date;
  return a.date > b.date;
}

// 목록 순서(PC 가 알려 준 순서)는 그대로 둔다. top = 위에 보일 것, rest = 접을 것
export function splitModels(list: Choice[]): { top: Choice[]; rest: Choice[] } {
  const best = new Map<string, { c: Choice; p: Parsed }>();
  for (const c of list) {
    const p = parseModel(c.provider, c.model);
    if (!p) continue;
    const k = `${c.device}|${c.provider}|${p.family}`, b = best.get(k);
    if (!b || newer(p, b.p)) best.set(k, { c, p });
  }
  const keep = new Set([...best.values()].map(v => key(v.c)));
  const top: Choice[] = [], rest: Choice[] = [];
  for (const c of list) (parseModel(c.provider, c.model) && !keep.has(key(c)) ? rest : top).push(c);
  return { top, rest };
}
