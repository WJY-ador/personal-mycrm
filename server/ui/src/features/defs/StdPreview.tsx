// 공통 구조 적용 검토(옛 loadPreview·stdChoose) — 미리보기를 받아 표준마다 보류·거절·편입. 성공·충돌(CONFLICT·DEF-INVALID) = 머리 한 줄 + 다시 받기,
// 그 밖 실패 = 그 카드에 문구(서버 msg 그대로, 연결 실패만 화면 문구). 고르지 않아도 다른 기능은 그대로.
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiErr } from "../../shared/api";
import type { UiCtx } from "../../shared/ctx";
import { PartFail } from "../../shared/PartFail";
import { PvCard } from "./PvCard";
import { StdDialog } from "./StdDialog";
import { PV_KEY, stdApi, type PvObj } from "./stdApi";
import { STD_DONE, STD_ERR } from "./text";

export function StdPreview({ ctx }: { ctx: UiCtx }) {
  const q = useQuery({ queryKey: PV_KEY, queryFn: stdApi.preview });
  const [msg, setMsg] = useState(""), [busy, setBusy] = useState(false);
  const [card, setCard] = useState<{ key: string; st: string; er: string } | null>(null);
  const [ask, setAsk] = useState<PvObj | null>(null);
  async function choose(o: PvObj, state: string) {
    setMsg(""); setCard({ key: o.std_key, st: "저장하고 있어요…", er: "" }); setBusy(true);
    try { await stdApi.choose(o, state); } catch (x) {
      const e = apiErr(x);
      if (e.code === "CONFLICT" || e.code === "DEF-INVALID") { setMsg(`표준 「${o.std_name}」 — ${STD_ERR[e.code]}`); setCard(null); await ctx.reload(); setBusy(false); return; }
      setCard({ key: o.std_key, st: "", er: STD_ERR[e.code] || (e.code === "OFFLINE" ? "서버에 연결하지 못했어요. 잠시 뒤 다시 해 보세요." : e.msg || "저장하지 못했어요. 다시 해 보세요.") });
      setBusy(false);
      return;
    }
    setMsg(`표준 「${o.std_name}」 — ${STD_DONE[state]}`); setCard(null);
    await ctx.reload();
    setBusy(false);
  }
  const pv = q.data;
  return (
    <section className="sec" aria-labelledby="std-pv-title"><h3 id="std-pv-title">공통 구조 적용 검토</h3>
      <p className="hint">표준 정의마다 편입·보류·거절을 골라요. 편입한 정의는 「표준 정의 보호」를 받아요. 고르지 않아도 다른 기능은 그대로예요.</p>
      <p id="std-msg" role="status" aria-atomic="true">{msg}</p>
      <div id="std-pv" aria-busy={!pv && !q.isError}>{q.isError || (pv && !Array.isArray(pv.objects))
        ? <PartFail err={q.isError ? { code: apiErr(q.error).code || "OFFLINE", msg: apiErr(q.error).msg } : { code: "OFFLINE", msg: "" }} what="편입 미리보기" />
        : !pv ? <p className="empty">미리보기를 불러오는 중이에요…</p>
        : <div className="spv">{pv.objects.map(o => <PvCard key={o.std_key} o={o} all={pv.objects} busy={busy} st={card?.key === o.std_key ? card.st : ""}
          er={card?.key === o.std_key ? card.er : ""} choose={choose} ask={setAsk} />)}</div>}</div>
      <StdDialog o={ask} close={() => setAsk(null)} go={o => { setAsk(null); void choose(o, "incorporated"); }} />
    </section>
  );
}
