// 추천 칸(2026-11-18 구조추천 명세 6.5) — 내 구조 설정 맨 위. 초안 카드마다 [적용] [이름 고치기] [빼기], 머리에 [구조 추천 받기].
// 추천을 만드는 일은 사용자의 AI(웹 대화, MCP)가 한다 — 버튼은 웹 AI 대화 입력칸에 정해진 요청을 채워 연다(보내기는 사용자). 웹 대화가 꺼져 있으면 안내 한 줄.
// 성공 = 머리 한 줄 + 추천 다시 받기 + 상태 다시 받기(적용하면 탭과 항목이 바뀐다). CONFLICT = 머리 한 줄 + 다시 받기, 그 밖 실패 = 그 카드에 서버 문구.
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { aiAsk } from "../../shared/aiAsk";
import { apiErr } from "../../shared/api";
import type { UiCtx } from "../../shared/ctx";
import { PartFail } from "../../shared/PartFail";
import { RecoCard } from "./RecoCard";
import { RECO_KEY, recoApi, type RecoDraft } from "./recoApi";
import { RECO_ASK, RECO_TEXT as T } from "./text";

export function Reco({ ctx }: { ctx: UiCtx }) {
  // 껍데기가 상태를 다시 받으면(S.generated, 대화에서 초안이 생긴 뒤 등) 추천도 다시 받는다 — 오브젝트 탭 목록 보기와 같은 방식
  const q = useQuery({ queryKey: [...RECO_KEY, ctx.state?.generated || ""], queryFn: recoApi.get }), qc = useQueryClient();
  const [msg, setMsg] = useState(""), [busy, setBusy] = useState(false);
  const [card, setCard] = useState<{ id: string; st: string; er: string } | null>(null);
  const chat = !!ctx.state?.switches?.webchat;
  async function run(d: RecoDraft, go: () => Promise<unknown>, done: (out: unknown) => string) {
    setMsg(""); setCard({ id: d.object_id, st: T.busy, er: "" }); setBusy(true);
    try {
      const out = await go();
      setMsg(`${d.label}: ${done(out)}`); setCard(null);
      await Promise.all([qc.invalidateQueries({ queryKey: RECO_KEY }), ctx.reload()]);
    } catch (x) {
      const e = apiErr(x);
      if (e.code === "CONFLICT") { setMsg(`${d.label}: ${T.conflict}`); setCard(null); await qc.invalidateQueries({ queryKey: RECO_KEY }); }
      else setCard({ id: d.object_id, st: "", er: e.code === "OFFLINE" ? T.offline : e.msg || T.fail });
    }
    setBusy(false);
  }
  const filled = (out: unknown) => {   // route_sync = 담을 규칙이 있는 적용만(서버 db.definition_apply). left = 한 번에 못 채운 수(매일 정리가 잇는다)
    const rs = (out as { route_sync?: { created?: number; left?: number } } | null)?.route_sync;
    return rs ? T.applied(rs.created || 0, rs.left || 0) : T.appliedPlain;
  };
  const ask = () => { if (!aiAsk.ask(RECO_ASK)) setMsg(T.askOff); };   // 대화 섬이 아직 안 떴으면(이름 관문 등) 안내 한 줄
  const r = q.data;
  return (
    <section className="sec" id="reco" aria-labelledby="reco-title"><h3 id="reco-title">{T.title}{r ? <span className="count">{r.drafts.length}</span> : null}</h3>
      <p className="hint">{T.lead}</p>
      {chat ? <p><button className="secondary" type="button" onClick={ask}>{T.ask}</button></p> : <p className="hint">{T.askOff}</p>}
      <p id="reco-msg" role="status" aria-atomic="true">{msg}</p>
      <div aria-busy={!r && !q.isError}>{q.isError ? <PartFail err={{ code: apiErr(q.error).code || "OFFLINE", msg: apiErr(q.error).msg }} what="구조 추천" />
        : !r ? <p className="empty">추천을 불러오는 중이에요…</p>
        : <>{r.suggest ? <p className="hint">{T.suggest(r.unattached)}</p> : null}
          {r.drafts.length ? <div className="spv">{r.drafts.map(d => <RecoCard key={`${d.object_id}:${d.proposal_id}`} d={d} busy={busy}
            st={card?.id === d.object_id ? card.st : ""} er={card?.id === d.object_id ? card.er : ""}
            apply={() => void run(d, () => recoApi.apply(d), filled)}
            rename={label => void run(d, () => recoApi.rename(d, label.trim()), () => T.renamed)}
            discard={() => void run(d, () => recoApi.discard(d), () => T.discarded)} />)}</div>
            : <p className="empty">{T.none}</p>}</>}</div>
    </section>
  );
}
