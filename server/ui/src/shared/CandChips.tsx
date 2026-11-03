// 판단 문장 표시(옛 app.html origin·decision·aiWordingChip) — 쓴 쪽 배지 · 결정 배지 · AI 문안 칩. 질문·기록·구조·지도·판단 검토가 같이 쓴다.
import type { Cand } from "./state";

export function OriginBadge({ c }: { c: Pick<Cand, "origin" | "edited_by_user"> }) {
  return <span className={`badge ${c.origin === "ai" ? "b-ai" : "b-memo"}`}>{c.origin === "ai" ? "AI가 쓴 문장" : "내가 쓴 메모"}{c.edited_by_user ? " · 내가 고침" : ""}</span>;
}

export function DecisionBadge({ status }: { status: string }) {
  if (status === "confirmed") return <span className="badge b-mine">확정한 판단</span>;
  if (status === "excluded") return <span className="badge b-off">반영 안 함</span>;
  return <span className="badge b-wait">아직 안 정함</span>;
}

// AI 가 쓴 문안을 사용자가 아직 승인하지 않은 후보. 구버전 서버(키 없음)에선 그리지 않는다.
export const AiWording = ({ c }: { c: Pick<Cand, "wording_approved" | "wording_by"> }) =>
  c.wording_approved === false && c.wording_by === "ai" ? <span className="chip o-ai">AI 문안</span> : null;
