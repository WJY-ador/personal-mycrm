// 이관 첫 화면(옛 migListHtml) — 스위치 안내 · 새 토큰 상자(받은 그 화면에서만) · 이관 토큰 · plan 목록(상태·항목 수·만료·오늘 사용량/한도).
// 토큰 원문은 이 컴포넌트 useState 에만 — plan 하나로 가거나 화면을 떠나면(unmount) 지운다. 꺼짐이면 받은 토큰도 그리지 않는다
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { apiErr } from "../../shared/api";
import { mdhm } from "../../shared/date";
import { LoadFail } from "../../shared/LoadFail";
import { TokenBox } from "../../shared/TokenBox";
import type { Done } from "./MigPlan";
import { migApi, type Plan } from "./migApi";
import { MigTokens } from "./MigTokens";
import { LOADING, MIG_ACT, MIG_ACTIONS, OFF } from "./text";
import { StateChip } from "./Why";

function PlanRow({ p }: { p: Plan }) {
  const acts = p.summary?.dry_run?.actions || {};
  const a = MIG_ACTIONS.filter(k => acts[k]).map(k => `${MIG_ACT[k]} ${acts[k]}`).join(" · ");
  const open = p.state === "staged" || p.state === "sealed", href = `#_setup/migration/${p.plan_id}`;
  const meta = [`${p.item_count}항목`, `${mdhm(p.created_at)} 올림`, open ? `${mdhm(p.expires_at)} 만료` : "", p.applied_at ? `${mdhm(p.applied_at)} 반영` : "", a].filter(Boolean).join(" · ");
  return (
    <li className="inrow"><a href={href}><StateChip st={p.state} /><b>{p.source_instance}</b><span className="tech"><code>{p.plan_id}</code></span></a>
      <span className="meta">{meta}{p.state === "applied" ? <> · <a href={href}>영수증 보기</a></> : null}</span>
      {p.via === "mcp" ? <span className="badge">대화에서 반영됨</span> : null}</li>
  );
}

export function MigList({ done }: { done: Done }) {
  const [tok, setTok] = useState<{ label: string; token: string } | null>(null);
  const t = useQuery({ queryKey: ["mig", "tokens"], queryFn: migApi.tokens });
  const p = useQuery({ queryKey: ["mig", "plans"], queryFn: migApi.plans });
  if (t.isError && !t.data) return <LoadFail err={apiErr(t.error)} what="이관 토큰" />;
  if (p.isError && !p.data) return <LoadFail err={apiErr(p.error)} what="이관 plan 목록" />;
  if (!t.data || !p.data) return <p className="hint">{LOADING}</p>;
  const T = t.data, plans = p.data.plans || [], L = p.data.limits;
  const off = !T.enabled ? OFF.list : !T.allowed ? OFF.deny : "";
  const lim = `오늘 반영 ${L.used_today} / ${L.daily}행 · plan당 ${L.plan_items}항목 · 열린 plan ${L.open_plans}개까지 · 보관 ${L.plan_days}일`;
  return (
    <>
      {t.isError ? <LoadFail err={apiErr(t.error)} what="이관 토큰" /> : null}
      {p.isError ? <LoadFail err={apiErr(p.error)} what="이관 plan 목록" /> : null}
      {off ? <p className="fnote">{off}</p> : null}
      {tok && !off ? <TokenBox title={`「${tok.label}」 이관 토큰`} region="새 이관 토큰" inputLabel="이관 토큰" token={tok.token} paste="PC의 이관 업로더에 붙여 넣으세요."
        copied="복사했어요. PC 업로더에 붙여 넣으세요." lost="잃어버리면 새로 발급" onDone={() => setTok(null)} /> : null}
      <MigTokens t={T} off={!!off} onToken={setTok} done={done} />
      <section className="sec"><h2 className="sh">plan <span className="speclabel">{lim}</span></h2>
        {plans.length ? <ul className="rows">{plans.map(x => <PlanRow key={x.plan_id} p={x} />)}</ul>
          : <div className="empty">아직 올라온 plan이 없어요. PC 업로더로 올리면 여기에 보여요.</div>}</section>
    </>
  );
}
