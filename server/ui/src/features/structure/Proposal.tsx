// 적용 전 제안(옛 proposalHtml) — 바뀌는 칸만 전 → 후(본문은 굵게만), 새 항목 제안이면 안내. [적용]·[제외] = 서버 item_decide 그대로(화면이 자동 확정하지 않는다).
import type { ReactNode } from "react";
import { clip } from "../../shared/clip";
import { mdhm } from "../../shared/date";
import { rich } from "../../shared/rich";
import { fieldVal } from "./model";
import type { ItemFull } from "./structApi";

export function Proposal({ it, busy, act }: { it: ItemFull; busy: boolean; act: (a: string) => void }) {
  const pr = it.proposal!, isNew = !it.revision, rows: ReactNode[] = [];
  const row = (k: string, a: unknown, b: unknown) => {
    if (JSON.stringify(a ?? "") === JSON.stringify(b ?? "")) return;
    rows.push(<dt key={`t${rows.length}`}>{k}</dt>, <dd key={`d${rows.length}`}>{a ? <><del>{rich(clip(String(a), 120))}</del> → </> : null}<ins>{rich(clip(String(b || "(비움)"), 200))}</ins></dd>);
  };
  if (!isNew) {
    row("제목", it.title, pr.title);
    row("본문", it.body, pr.body);
    for (const f of it.fields.filter(f => f.value_type !== "reference")) row(f.label, fieldVal(f, (it.data || {})[f.key]), fieldVal(f, (pr.data || {})[f.key]));
    for (const f of it.fields.filter(f => f.value_type === "reference")) {
      const a = (it.links || []).filter(l => l.field_key === f.key), b = (pr.links || []).filter(l => l.field_key === f.key);
      if (JSON.stringify(a.map(l => l.target_id).sort()) !== JSON.stringify(b.map(l => l.target_id).sort()))
        rows.push(<dt key={`t${rows.length}`}>{f.label}</dt>, <dd key={`d${rows.length}`}>{a.length}개 → <ins>{b.length}개</ins></dd>);
    }
  }
  return (
    <div className="proposal"><b>제안이 있어요</b> <span className="tech">{mdhm(pr.proposed_at)}</span>
      {isNew ? <p className="hint" style={{ margin: ".3rem 0 0" }}>연결한 AI 대화에서 새로 제안한 항목이에요. 적용하면 목록에 들어가요.</p>
        : rows.length ? <dl className="diff">{rows}</dl> : <p className="hint" style={{ margin: ".3rem 0 0" }}>바뀌는 내용이 없어요.</p>}
      <div className="pacts"><button className="primary" type="button" disabled={busy} onClick={() => act("apply")}>적용</button>
        <button className="secondary" type="button" disabled={busy} onClick={() => act("discard")}>제외</button></div></div>
  );
}
