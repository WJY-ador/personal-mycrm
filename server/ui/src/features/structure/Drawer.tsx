// 항목 서랍(옛 openDrawer·drawerHtml·itemAct·trashDel) — 전문·필드·승격 사실·제안(diff)·결정·관계·이력. 쓰기 = /api/item/decide · /api/trash/move,
// 실패 문구는 서버 msg 그대로(충돌만 화면 문구). 승격 조건은 사실일 뿐 — 남길지는 사용자가 버튼으로 정한다(화면이 자동 확정하지 않는다).
import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiErr } from "../../shared/api";
import type { UiCtx } from "../../shared/ctx";
import { itemDecide, trashErr, trashMove, TRASH_ASK, TRASH_DONE } from "../../shared/item";
import { PartFail } from "../../shared/PartFail";
import { RELOAD, postMsg } from "../../shared/postErr";
import { rich } from "../../shared/rich";
import type { AppState } from "../../shared/state";
import { DecisionChip, SelectChips } from "./Cards";
import { Links } from "./Links";
import { CONFLICT_TEXT, defById, eventLabel, fieldVal, ITEM_SAVED, TAB, viewOf } from "./model";
import { Proposal } from "./Proposal";
import { fetchItem, itemKey, type ItemFull } from "./structApi";

type Props = { ctx: UiCtx; S: AppState; id: string; open: (id: string, quote?: string) => void; gone: (msg: string, to: string) => void };

export function Drawer({ ctx, S, id, open, gone }: Props) {
  const q = useQuery({ queryKey: itemKey(id), queryFn: () => fetchItem(id) });
  const [busy, setBusy] = useState(false);
  const [st, setSt] = useState(""), [er, setEr] = useState("");
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => { if (q.data && window.matchMedia?.("(max-width: 900px)").matches) box.current?.scrollIntoView?.({ block: "start" }); }, [q.data?.id]);
  if (q.isError) return <PartFail err={apiErr(q.error)} what="이 항목" />;
  if (!q.data) return <p className="empty">불러오는 중이에요…</p>;
  const it: ItemFull = q.data, d = it.object, isNew = !it.revision, cur = viewOf(it), back = `#${TAB}/${d.id}`;
  const def = defById(S, d.id), trashOn = !!S.switches?.trash;
  const plain = it.fields.filter(f => f.value_type !== "reference").map(f => [f.label, fieldVal(f, (cur.data || {})[f.key])]).filter(x => x[1]);

  async function act(a: string) {
    setEr(""); setSt("저장하고 있어요…"); setBusy(true);
    let j: { deleted?: boolean };
    try {
      j = await itemDecide({ item_id: it.id, expected_revision: it.revision, action: a, ...(a === "apply" || a === "discard" ? { proposal_id: it.proposal!.proposal_id } : {}) });
    } catch (x) {
      const e = apiErr(x);
      setBusy(false); setSt("");
      setEr(e.code === "OFFLINE" ? "서버에 연결하지 못했어요. 새로 고침해 확인해 주세요." : e.code === "CONFLICT" ? CONFLICT_TEXT : e.msg || "저장하지 못했어요.");
      return;
    }
    if (j.deleted) { gone(ITEM_SAVED[a] || "저장했어요.", back); await ctx.reload(); return; }   // 새 항목 제안을 제외 — 카드가 사라진다
    setSt(ITEM_SAVED[a] || "저장했어요.");
    await ctx.reload();   // 상태를 다시 받아 카드·서랍을 같이 그린다
    setBusy(false);
  }
  async function del() {
    if (!window.confirm(TRASH_ASK)) return;
    setEr(""); setBusy(true);
    try { await trashMove("item", it.id, it.revision); } catch (x) {
      const e = apiErr(x);
      setBusy(false);
      if (e.code !== "AXIS-IN-POLICY" && RELOAD.has(e.code)) { setEr(postMsg(e)); await ctx.reload(); } else setEr(trashErr(e));
      return;
    }
    gone(TRASH_DONE, back);
    await ctx.reload();
  }
  const b = (cls: string, a: string, label: string, off = false) => <button key={a} className={cls} type="button" disabled={busy || off} onClick={() => act(a)}>{label}</button>;
  return (
    <div ref={box}>
      <div className="eyebrow">{d.label || "항목"}{isNew ? " · 새 제안" : ` · r${it.revision}`}</div>
      <div className="labels" style={{ marginTop: ".4rem" }}>{cur.code ? <span className="chip code">{cur.code}</span> : null}<SelectChips it={cur} d={def} /><DecisionChip it={it} /></div>
      <h4>{cur.title || "(제목 없음)"}</h4>{cur.body ? <div className="pbody">{rich(cur.body)}</div> : null}
      {plain.length ? <dl className="pf">{plain.map(([k, v], i) => [<dt key={`t${i}`}>{k}</dt>, <dd key={`d${i}`}>{v}</dd>])}</dl> : null}
      {it.promotion ? <p className="promo">승격 조건 — 확정 근거 <b>{it.promotion.confirmed_claims}/{it.promotion.confirmed_claims_min}</b>
        {it.promotion.distinct_events_min ? <> · {eventLabel(S, def)} <b>{it.promotion.distinct_events}/{it.promotion.distinct_events_min}</b></> : null}
        {` · ${it.promotion.met ? "충족" : "아직 미충족"}. 남길지는 내가 정해요.`}</p> : null}
      {it.proposal ? <Proposal it={it} busy={busy} act={act} /> : null}
      {!isNew && trashOn ? <div className="pacts" role="group" aria-label={`${d.label || "항목"} 동작`}>
        {it.semantic_kind === "principle" && it.decision !== "confirmed" ? b("primary", "confirm", "남기기") : null}
        <button className="secondary" type="button" disabled={busy} onClick={del}>삭제</button></div>
        : it.semantic_kind === "principle" && !isNew ? <div className="pacts" role="group" aria-label={`${d.label || "기준"} 결정`}>
          {b("primary", "confirm", "남기기", it.decision === "confirmed")}{b("secondary", "exclude", "반영 안 함", it.decision === "excluded")}
          {b("tertiary", "pending", "되돌리기", it.decision === "pending")}</div> : null}
      <p className="pstatus" role="status" aria-atomic="true">{st}</p><p className="perror" role="alert" aria-atomic="true">{er}</p>
      <Links S={S} it={it} cur={cur} open={open} />
    </div>
  );
}
