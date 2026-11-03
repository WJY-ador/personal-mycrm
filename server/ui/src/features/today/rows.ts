// 「오늘」 줄 만들기(옛 todayRows) — 대기(받은 시각) + 승인해 저장된 내 글(ingest_kind=inbox · 저장된 시각) + 장치 활동(받은 시각).
// 새것부터, 같은 시각이면 들어온 순서. day = 들어온 날(KST)
import { actLabel, type Act } from "../../shared/activity";
import { dOnly, md, mdhm, timeOf } from "../../shared/date";
import { readOk, type AppState } from "../../shared/state";
import { INBOX_KIND, inboxTitle } from "./text";
import type { Entry } from "./todayApi";

export type Row = { day: string; at: string; st: "대기" | "보관됨"; kind: string; ai: boolean; title: string; href: string; key: string; act: boolean; meta: string[] };

export const kstDay = (iso: string | null | undefined) => { const t = timeOf(iso); return t ? new Date(t).toLocaleDateString("sv-SE", { timeZone: "Asia/Seoul" }) : ""; };
export const kstToday = () => new Date().toLocaleDateString("sv-SE", { timeZone: "Asia/Seoul" });

export function todayRows(S: AppState, pend: Entry[], acts: Act[]): Row[] {
  const out: Omit<Row, "day">[] = [];
  for (const e of pend) out.push({ at: e.received_at, st: "대기", kind: INBOX_KIND[e.kind] || e.kind, ai: e.kind === "self_summary", act: false,
    title: inboxTitle(S, e), href: `#_today/inbox/${e.id}`, key: "inbox:" + e.id,
    meta: [e.device ? e.device.label : "", `${mdhm(e.received_at)} 받음`, e.expires_at ? `${md(e.expires_at)} 만료 예정` : "", e.execution === "unattended" ? "무인 실행" : ""] });
  for (const r of readOk(S, "journal") ? S.journal || [] : []) if (r.ingest_kind === "inbox") out.push({ at: r.created, st: "보관됨", kind: "내 글", ai: false, act: false,
    title: r.title || r.excerpt || "(제목 없음)", href: `#_me/journal/${r.id}`, key: "rec:" + r.id, meta: [`${mdhm(r.created)} 저장`, r.source_date ? `원래 쓴 날 ${dOnly(r.source_date)}` : ""] });
  for (const a of acts) out.push({ at: a.received_at || "", st: "보관됨", kind: a.action_label || actLabel(S.activity_ui?.actions, a.action), ai: false, act: true,
    title: a.source ? a.source.name : "활동", href: `#_obj/activity/${a.id}`, key: "act:" + a.id,
    meta: [a.occurred_on ? `행동한 날 ${dOnly(a.occurred_on)}` : "행동한 날 미확인", (a.people || []).map(p => p.alias).join(", ")] });
  return out.map((x, i) => [x, i] as const).sort((p, q) => timeOf(q[0].at) - timeOf(p[0].at) || p[1] - q[1]).map(([x]) => ({ ...x, day: kstDay(x.at) }));
}
