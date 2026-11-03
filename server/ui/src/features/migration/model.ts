// 반영 확인에 쓸 개수(옛 migTally) — 체크한 기준만 반영 대상
import type { Detail } from "./migApi";

export function tally(pl: Detail) {
  const xs = pl.items || [], take = (x: Detail["items"][number]) => !x.needs_check || x.checked;
  const n = (a: string) => xs.filter(x => x.action === a).length;
  return {
    insert: xs.filter(x => x.action === "insert" && take(x)).length, noop: xs.filter(x => x.action === "noop" && take(x)).length,
    unchecked: xs.filter(x => x.needs_check && !x.checked).length, checks: xs.filter(x => x.needs_check).length,
    warn: n("warn"), conflict: n("conflict"), reject: n("reject"),
  };
}

export const left = (L: { daily: number; used_today: number }) => Math.max(0, L.daily - L.used_today);
