// 새 항목 제안(옛 proposalHtml) — 안내 + [적용]·[제외] = 서버 item_decide 그대로(화면이 자동 확정하지 않는다).
import { mdhm } from "../../shared/date";
import type { ItemFull } from "./structApi";

export function Proposal({ it, busy, act }: { it: ItemFull; busy: boolean; act: (a: string) => void }) {
  return (
    <div className="proposal"><b>제안이 있어요</b> <span className="tech">{mdhm(it.proposal!.proposed_at)}</span>
      <p className="hint" style={{ margin: ".3rem 0 0" }}>연결한 AI 대화에서 새로 제안한 항목이에요. 적용하면 목록에 들어가요.</p>
      <div className="pacts"><button className="primary" type="button" disabled={busy} onClick={() => act("apply")}>적용</button>
        <button className="secondary" type="button" disabled={busy} onClick={() => act("discard")}>제외</button></div></div>
  );
}
