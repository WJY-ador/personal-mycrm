// 이관 토큰 칸(옛 migListHtml 위쪽) — 꺼짐·허용 목록 밖이면 [새 토큰] 대신 안내. 발급 = 앞 토큰이 살아 있으면 확인 1번. 원문은 부모 useState(토큰 상자)
import { useState } from "react";
import { apiErr } from "../../shared/api";
import { mdhm } from "../../shared/date";
import type { Done } from "./MigPlan";
import { migApi, type Tok, type Tokens } from "./migApi";
import { ASK, DONE, MIG_TOK_WARN, plainErr } from "./text";
import css from "./Migration.module.css";

function tokState(x: Tok): [string, string] {
  if (x.revoked_at) return ["st-off", "폐기됨"];
  if (!x.active) return ["st-off", "만료"];
  return ["st-mine", "사용 중"];
}

type Props = { t: Tokens; off: boolean; onToken: (x: { label: string; token: string }) => void; done: Done };

export function MigTokens({ t, off, onToken, done }: Props) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const toks = t.tokens || [];
  async function run(call: () => Promise<unknown>, after: (r: unknown) => void, text: string) {
    setErr(""); setBusy(true);
    let r: unknown;
    try { r = await call(); } catch (x) { setBusy(false); setErr(plainErr(apiErr(x))); return; }
    setBusy(false);
    after(r);
    await done(text);
  }
  const issue = () => {
    if (toks.some(x => x.active) && !window.confirm(ASK.tokNew)) return;
    void run(migApi.tokNew, r => { const j = r as { token?: string; info?: { label?: string } }; onToken({ label: j.info?.label || "이관 업로더", token: j.token || "" }); }, DONE.tokNew);
  };
  const revoke = (id: string) => { if (window.confirm(ASK.tokRevoke)) void run(() => migApi.tokRevoke(id), () => {}, DONE.tokRevoke); };
  return (
    <section className="sec"><h2 className="sh">이관 토큰</h2>
      <p className="hint">{`PC 업로더가 plan을 올릴 때만 써요. ${t.token_days}일 뒤 만료돼요. ${MIG_TOK_WARN}`}</p>
      {off ? <p className="hint">이관이 켜지면 여기서 새 토큰을 발급해요.</p>
        : <div className="frow" style={{ margin: "0 0 .6rem" }}><button type="button" className="primary" disabled={busy} onClick={issue}>새 토큰</button></div>}
      {toks.length ? <ul className="rows">{toks.map(x => {
        const [c, s] = tokState(x);
        return (
          <li key={x.id} className={css.tok}><div className={css.head}><span className={`chip ${c}`}>{s}</span><b>{x.label}</b>
            {x.active ? <button type="button" className="secondary small" disabled={busy} onClick={() => revoke(x.id)}>폐기</button> : null}</div>
            <span className="meta">{`${mdhm(x.created_at)} 발급 · ${x.revoked_at ? `${mdhm(x.revoked_at)} 폐기` : `${mdhm(x.expires_at)} 만료`} · 마지막 사용 ${x.last_used_at ? mdhm(x.last_used_at) : "아직 없음"}`}</span></li>
        );
      })}</ul> : <div className="empty">아직 발급한 이관 토큰이 없어요.</div>}
      <p className="ferr" role="alert" aria-atomic="true">{err}</p></section>
  );
}
