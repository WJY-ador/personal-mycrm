// 새 항목 제안 서랍(옛 openDrawer·drawerHtml·itemAct) — 적용 전 제안(revision 0)의 제목·본문·필드·연결할 대상 + [적용]·[제외].
// 적용된 항목은 「나」 의 그 탭에서 본다(옛 주소는 라우터가 replace — shared/route). 쓰기 = /api/item/decide, 실패 문구는 서버 msg 그대로(충돌만 화면 문구).
import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiErr } from "../../shared/api";
import type { UiCtx } from "../../shared/ctx";
import { itemDecide } from "../../shared/item";
import { PartFail } from "../../shared/PartFail";
import { rich } from "../../shared/rich";
import type { AppState } from "../../shared/state";
import { SelectChips } from "./Cards";
import { Links } from "./Links";
import { CONFLICT_TEXT, defById, fieldVal, ITEM_SAVED, TAB, viewOf } from "./model";
import { Proposal } from "./Proposal";
import { fetchItem, itemKey, type ItemFull } from "./structApi";

type Props = { ctx: UiCtx; S: AppState; id: string; open: (id: string, quote?: string) => void; gone: (msg: string, to: string) => void };

export function Drawer({ ctx, S, id, open, gone }: Props) {
  const q = useQuery({ queryKey: itemKey(id), queryFn: () => fetchItem(id) });
  const [busy, setBusy] = useState(false);
  const [st, setSt] = useState(""), [er, setEr] = useState("");
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => { if (q.data && window.matchMedia?.("(max-width: 900px)").matches) box.current?.scrollIntoView?.({ block: "start" }); }, [q.data?.id]);
  if (q.isError && !q.data) return <PartFail err={apiErr(q.error)} what="이 항목" />;
  if (!q.data) return <p className="empty">불러오는 중이에요…</p>;
  const it: ItemFull = q.data, d = it.object, cur = viewOf(it), back = `#${TAB}/${d.id}`;
  const plain = it.fields.filter(f => f.value_type !== "reference").map(f => [f.label, fieldVal(f, (cur.data || {})[f.key])]).filter(x => x[1]);

  async function act(a: string) {
    setEr(""); setSt("저장하고 있어요…"); setBusy(true);
    let j: { deleted?: boolean };
    try {
      j = await itemDecide({ item_id: it.id, expected_revision: it.revision, action: a, proposal_id: it.proposal!.proposal_id });
    } catch (x) {
      const e = apiErr(x);
      setBusy(false); setSt("");
      setEr(e.code === "OFFLINE" ? "서버에 연결하지 못했어요. 새로 고침해 확인해 주세요." : e.code === "CONFLICT" ? CONFLICT_TEXT : e.msg || "저장하지 못했어요.");
      return;
    }
    if (j.deleted) { gone(ITEM_SAVED[a] || "저장했어요.", back); await ctx.reload(); return; }   // 제안을 제외 — 카드가 사라진다
    setSt(ITEM_SAVED[a] || "저장했어요.");
    await ctx.reload();   // 적용 = 상태를 다시 받으면 적용된 항목이 되어 라우터가 「나」 의 그 항목으로 replace 한다(shared/route)
    setBusy(false);
  }
  return (
    <div ref={box}>
      {q.isError ? <PartFail err={apiErr(q.error)} what="이 항목" /> : null}
      <div className="eyebrow">{d.label || "항목"} · 새 제안</div>
      <div className="labels" style={{ marginTop: ".4rem" }}>{cur.code ? <span className="chip code">{cur.code}</span> : null}<SelectChips it={cur} d={defById(S, d.id)} /></div>
      <h4>{cur.title || "(제목 없음)"}</h4>{cur.body ? <div className="pbody">{rich(cur.body)}</div> : null}
      {plain.length ? <dl className="pf">{plain.map(([k, v], i) => [<dt key={`t${i}`}>{k}</dt>, <dd key={`d${i}`}>{v}</dd>])}</dl> : null}
      {it.proposal ? <Proposal it={it} busy={busy} act={act} /> : null}
      <p className="pstatus" role="status" aria-atomic="true">{st}</p><p className="perror" role="alert" aria-atomic="true">{er}</p>
      <Links S={S} it={it} cur={cur} open={open} />
    </div>
  );
}
