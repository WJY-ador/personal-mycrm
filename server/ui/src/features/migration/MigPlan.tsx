// plan 하나(옛 migPlanLoad·migCheck·migBody·migApply·migCancel·migFail) — 확인(sealed) · 영수증(applied) · 그 밖 상태 안내.
// 기준 체크 = 한 번에 하나(응답 = 새 plan). 본문은 펼칠 때 하나씩 받아 이 화면 useState 에만(떠나면 지운다). 오류는 확인 화면 안에 남긴다
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { apiErr, type ApiError } from "../../shared/api";
import { LoadFail } from "../../shared/LoadFail";
import { postMsg } from "../../shared/postErr";
import { migApi, type PItem } from "./migApi";
import type { BodyState } from "./MigItem";
import { MigReceipt } from "./MigReceipt";
import { MigSealed } from "./MigSealed";
import { ASK, DONE, LOADING } from "./text";

export type Done = (text: string, o?: { at?: string; bad?: boolean }) => Promise<void>;
type Props = { pid: string; done: Done };
const RE = new Set(["PLAN-EXPIRED", "PLAN-STATE"]);   // 상태가 바뀌었다 — 다시 받아 그린다(오류 문구는 남긴다)

export function MigPlan({ pid, done }: Props) {
  const qc = useQueryClient();
  const d = useQuery({ queryKey: ["mig", "plan", pid], queryFn: () => migApi.plan(pid) });
  const l = useQuery({ queryKey: ["mig", "plans"], queryFn: migApi.plans });
  const applied = d.data?.state === "applied";
  const r = useQuery({ queryKey: ["mig", "receipt", pid], queryFn: () => migApi.receipt(pid), enabled: applied });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<ApiError | null>(null);
  const [open, setOpen] = useState<Set<number>>(new Set());
  const [bodies, setBodies] = useState<Record<number, BodyState>>({});
  if (d.isError) return <LoadFail err={apiErr(d.error)} what="이관 plan" />;
  if (!d.data || (!l.data && !l.isError)) return <p className="hint">{LOADING}</p>;
  const pl = d.data;
  if (applied) return r.isError ? <LoadFail err={apiErr(r.error)} what="영수증" /> : r.data ? <MigReceipt pl={pl} r={r.data} /> : <p className="hint">{LOADING}</p>;
  const on = !!(l.data && l.data.enabled && l.data.allowed), L = l.data?.limits || null;

  async function fail(e: ApiError) {
    if (e.code === "NAME-REQUIRED" || e.code === "NOT-FOUND") return done(postMsg(e), { bad: true });   // 옛 coreFail — 머리 문구 + 상태 다시 받기
    setErr(e);
    if (RE.has(e.code)) await d.refetch();
    setTimeout(() => document.getElementById("mig-err")?.scrollIntoView?.({ block: "nearest" }), 0);
  }
  async function check(x: PItem, v: boolean) {
    if (busy) return;
    setBusy(true); setErr(null);
    try {
      qc.setQueryData(["mig", "plan", pid], await migApi.check(pid, x.seq, v));
    } catch (e) { await fail(apiErr(e)); }
    setBusy(false);
    setTimeout(() => document.querySelector<HTMLInputElement>(`input[data-seq="${x.seq}"]`)?.focus(), 0);   // 한 번에 하나 — 잠깐 막았던 상자로 돌아간다
  }
  async function body(x: PItem) {
    const s = x.seq;
    if (open.has(s)) { setOpen(o => { const n = new Set(o); n.delete(s); return n; }); return; }
    setOpen(o => new Set(o).add(s));
    if (bodies[s] && !("error" in bodies[s]!)) return;
    setBodies(b => ({ ...b, [s]: undefined }));
    try {
      const j = await migApi.item(pid, s);
      setBodies(b => ({ ...b, [s]: j }));
    } catch { setBodies(b => ({ ...b, [s]: { error: "본문을 불러오지 못했어요. 접었다가 다시 열어 보세요." } })); }   // 다시 열면 다시 받는다
  }
  async function apply() {
    if (!pl.plan_hash) return;
    setBusy(true); setErr(null);
    let j;
    try { j = await migApi.apply(pid, pl.plan_hash); } catch (e) { setBusy(false); return fail(apiErr(e)); }
    setBusy(false);
    await done(j?.already_applied ? DONE.again : DONE.apply);
  }
  async function cancel() {
    if (!window.confirm(ASK.cancel)) return;
    setBusy(true);
    try { await migApi.cancel(pid); } catch (e) { setBusy(false); return fail(apiErr(e)); }
    setBusy(false);
    await done(DONE.cancel, { at: "#_setup/migration" });
  }
  return <MigSealed pl={pl} L={L} on={on} busy={busy} err={err} open={open} bodies={bodies} onCheck={check} onBody={body} onApply={apply} onCancel={cancel} />;
}
