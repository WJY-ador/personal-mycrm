// Setup 「연결 장치」(옛 renderDevices·devHtml) — 새 장치 연결 · 장치 카드. 연결·재발급 응답의 토큰 원문은 이 화면 useState 에만 두고
// [붙여 넣었어요 · 지우기]·화면을 떠나면(unmount) 지운다 — 상태·캐시·저장소·주소·결과 문구에 넣지 않는다.
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { apiErr } from "../../shared/api";
import { Crumbs } from "../../shared/Crumbs";
import type { ScreenProps } from "../../shared/ctx";
import { Flash, useFlash } from "../../shared/Flash";
import { LoadFail } from "../../shared/LoadFail";
import { postMsg, RELOAD } from "../../shared/postErr";
import { TokenBox } from "../../shared/TokenBox";
import { DevCard } from "./DevCard";
import { devApi } from "./devApi";
import { DONE, LEAD, LOADING } from "./text";
import css from "./Devices.module.css";

export function DevicesScreen({ ctx }: ScreenProps) {
  const S = ctx.state!;
  const { msg, say } = useFlash(ctx);
  const [tok, setTok] = useState<{ label: string; token: string } | null>(null);
  const [label, setLabel] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const q = useQuery({ queryKey: ["devices"], queryFn: devApi.list });
  const done = async (t: string) => { say(t); await ctx.reload(); };
  const fail = async (t: string) => { say(t, true); await ctx.reload(); };
  async function connect(e: React.FormEvent) {
    e.preventDefault();
    const v = label.trim();
    setErr("");
    if (!v) return setErr("장치 이름을 적어 주세요.");
    setBusy(true);
    let r;
    try {
      r = await devApi.connect(v);
    } catch (x) {
      const er = apiErr(x);
      setBusy(false);
      if (RELOAD.has(er.code)) return fail(postMsg(er));
      return setErr(postMsg(er));
    }
    setBusy(false);
    setLabel("");
    setTok({ label: r.device?.label || v, token: r.token || "" });
    await done(DONE.connect);
  }
  let body;
  if (q.isError && !q.data) body = <LoadFail err={apiErr(q.error)} what="연결 장치" />;
  else if (!q.data) body = <p className="hint">{LOADING}</p>;
  else {
    const j = q.data, ch = j.choices, ds = j.devices || [], full = j.active >= j.max;
    body = (
      <>
        {q.isError ? <LoadFail err={apiErr(q.error)} what="연결 장치" /> : null}
        {tok ? <TokenBox title={`${tok.label} 토큰`} region="새 토큰" inputLabel="토큰" token={tok.token} paste="로컬 에이전트의 연결 단계에 붙여 넣으세요."
          copied="복사했어요. 로컬 에이전트에 붙여 넣으세요." lost="잃어버리면 재발급" onDone={() => setTok(null)} /> : null}
        {j.switches?.imports ? null : <p className={`fnote ${css.off}`}>지금은 서버가 장치에서 보내는 자료를 받지 않아요(준비 중). 연결은 미리 해 둘 수 있어요.</p>}
        <form className="fform" noValidate onSubmit={connect}><label htmlFor="dev-label">새 장치 이름</label>
          <div className="frow" style={{ margin: 0 }}><input className="finput" id="dev-label" name="label" type="text" maxLength={80} autoComplete="off" aria-describedby="dev-label-help"
            style={{ flex: "1 1 14rem" }} disabled={full} value={label} onChange={e => setLabel(e.target.value)} />
            <button className="primary" type="submit" disabled={full || busy}>연결하기</button></div>
          <p className="hint" id="dev-label-help">{`이 PC를 알아볼 이름이에요(예: 집 노트북). 실명이나 회사 이름은 넣지 마세요. 연결하면 토큰을 한 번만 보여 줘요. 토큰은 ${ch.token_days}일 뒤 만료돼요.`}</p>
          {full ? <p className="fnote">{`연결된 장치가 ${j.max}대라 더 연결할 수 없어요. 쓰지 않는 장치를 해제하세요.`}</p> : null}
          <p className="ferr" role="alert" aria-atomic="true">{err}</p></form>
        <section className="sec"><h2 className="sh">장치 <span className="speclabel">연결 {j.active} / {j.max}</span></h2>
          {ds.length ? <div className="cards">{ds.map(d => <DevCard key={d.id} d={d} ch={ch} items={S.items || []} actions={S.activity_ui?.actions}
            onToken={setTok} done={done} fail={fail} />)}</div> : <div className="empty">아직 연결한 장치가 없어요.</div>}</section>
      </>
    );
  }
  return (
    <div className="paper sheet"><Crumbs xs={[["#_me", "나"], ["", "연결 장치"]]} /><Flash msg={msg} /><h2 className="title">연결 장치</h2>
      <p className="hint">{LEAD}</p>
      <p className="hint"><a href="/download">PC 앱 설치</a>, 옛 자료 옮기기는 <a href="#_setup/migration">이관</a></p>
      <div>{body}</div></div>
  );
}
