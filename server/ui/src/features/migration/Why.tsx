// 사유 · 상태 칩 · action 칩 — 사람 말 + 서버 코드(작게)
import { MIG_ACT, MIG_STATE, MIG_WHY } from "./text";
import css from "./Migration.module.css";

export const Why = ({ r }: { r: string | null | undefined }) => (r ? <>{MIG_WHY[r] || r} <span className="tech"><code>{r}</code></span></> : null);

export function StateChip({ st }: { st: string }) {
  const [c, t] = MIG_STATE[st] || ["", st];
  return <span className={`chip ${c}`}>{t}</span>;
}

export const ActChip = ({ a }: { a: string }) => <span className={`chip ${css["mig-" + a] || ""}`}>{MIG_ACT[a] || a}</span>;
