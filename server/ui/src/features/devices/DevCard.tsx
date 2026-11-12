// 장치 카드(옛 devCard) — 상태 칩 · 연결한 날·토큰 만료(또는 해제한 날)·마지막 연결 · 허용 규칙 한 줄 · [토큰 재발급]·[연결 해제]·허용 규칙 바꾸기
import { useState } from "react";
import { apiErr } from "../../shared/api";
import { actLabel } from "../../shared/activity";
import { md, mdhm } from "../../shared/date";
import { postMsg, RELOAD } from "../../shared/postErr";
import type { Item } from "../../shared/state";
import { devApi, type Choices, type Device, type Permit, type Policy } from "./devApi";
import { PolicyForm } from "./PolicyForm";
import { ASK, DONE, PERMIT_ASK, PERMIT_BTN, PERMIT_NOTE, aiName } from "./text";
import css from "./Devices.module.css";

function status(d: Device): [string, string] {
  if (!d.active) return ["st-off", "연결 해제됨"];
  if (d.token_revoked_at) return ["st-off", "토큰 폐기됨"];
  if (d.token_expires_at && new Date(d.token_expires_at) < new Date()) return ["st-wait", "토큰 만료, 재발급 필요"];
  return ["st-mine", "연결됨"];
}

function policyText(pol: Policy, ch: Choices, actions?: Record<string, string>) {
  const a = (pol.actions || []).map(x => actLabel(actions, x)).join(", ") || "없음";
  const t = (pol.transform_versions || []).map(k => (ch.transforms || []).find(x => x.key === k)?.label || k).join(", ") || "없음";
  return `행동 ${a}, 받는 것 ${t}, 축 ${(pol.axes || []).length}개`;
}

export type CardProps = {
  d: Device; ch: Choices; items: Item[]; actions?: Record<string, string>; permits?: Permit[];
  onToken: (t: { label: string; token: string }) => void; done: (t: string) => Promise<void>; fail: (t: string) => Promise<void>;
};

export function DevCard({ d, ch, items, actions, permits = [], onToken, done, fail }: CardProps) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [cls, txt] = status(d);
  async function act(k: "reissue" | "revoke") {
    if (!window.confirm(ASK[k])) return;
    setErr(""); setBusy(true);
    let r: { token?: string } | unknown;
    try {
      r = k === "reissue" ? await devApi.reissue(d.id) : await devApi.revoke(d.id);
    } catch (x) {
      const e = apiErr(x);
      setBusy(false);
      if (RELOAD.has(e.code)) return fail(postMsg(e));
      return setErr(postMsg(e));
    }
    setBusy(false);
    if (k === "reissue") onToken({ label: d.label, token: (r as { token?: string })?.token || "" });
    await done(DONE[k]);
  }
  // J(JD3): 이 PC 의 AI 대화 허용 해제 — 공급자마다 버튼 하나. 허용이 없으면(또는 대화 기능이 꺼져 있으면) 줄 자체가 없다
  const providers = [...new Set(permits.filter(p => p.device_id === d.id).map(p => p.provider))];
  async function unpermit(provider: string) {
    if (!window.confirm(PERMIT_ASK(provider))) return;
    setErr(""); setBusy(true);
    try { await devApi.revokePermit(d.id, provider); }
    catch (x) {
      const e = apiErr(x);
      setBusy(false);
      if (RELOAD.has(e.code)) return fail(postMsg(e));
      return setErr(postMsg(e));
    }
    setBusy(false);
    await done(DONE.permit);
  }
  return (
    <article className={`card ${css.card}`}><div className="labels"><span className={`chip ${cls}`}>{txt}</span></div><h3>{d.label}</h3>
      <dl className="kv"><dt>연결한 날</dt><dd>{md(d.created_at)}</dd>
        {d.active ? <><dt>토큰 만료</dt><dd>{md(d.token_expires_at)}</dd></> : <><dt>해제한 날</dt><dd>{md(d.revoked_at)}</dd></>}
        <dt>마지막 연결</dt><dd>{d.last_used_at ? mdhm(d.last_used_at) : "아직 없음"}</dd></dl>
      <p className="hint">{policyText(d.policy || { actions: [], transform_versions: [], axes: [] }, ch, actions)}</p>
      {d.active ? <><div className="pacts"><button type="button" className="secondary" disabled={busy} onClick={() => act("reissue")}>토큰 재발급</button>
        <button type="button" className="secondary" disabled={busy} onClick={() => act("revoke")}>연결 해제</button></div>
        {providers.length ? <div className={css.permits} data-permits=""><p className="hint">{PERMIT_NOTE(providers.map(aiName).join(", "))}</p>
          <div className="pacts">{providers.map(p => <button key={p} type="button" className="secondary" disabled={busy} onClick={() => unpermit(p)}>{PERMIT_BTN(p)}</button>)}</div></div> : null}
        <PolicyForm key={d.policy_revision} d={d} ch={ch} items={items} done={done} fail={fail} /></>
        : <p className="hint">해제한 장치는 되살리지 않아요(새로 연결해요). 이미 받은 활동과 글은 남아요.</p>}
      <p className="ferr" role="alert" aria-atomic="true">{err}</p></article>
  );
}
