// 저장 승인 대기 글 하나(옛 inboxOne) — 종류·상태 · 제목 · 보낸 장치·받은 때·만료·원래 쓴 때·실행·붙을 활동 · AI 생성 정보 · 본문 · [승인]·[제외](대기일 때만).
// 승인 안내 = 서버 문장(approve_notice) 그대로, 없으면 내 글 안내. 승인할 수 없으면(만료·처리됨·더 새 개정) 승인 버튼을 끈다. 성공 = 「오늘」
import { useQuery } from "@tanstack/react-query";
import { Fragment, useState } from "react";
import { apiErr } from "../../shared/api";
import type { UiCtx } from "../../shared/ctx";
import { dOnly, mdhm } from "../../shared/date";
import { LoadFail } from "../../shared/LoadFail";
import { postMsg, RELOAD } from "../../shared/postErr";
import { rich } from "../../shared/rich";
import { GEN_LABEL, GEN_VALUE, INBOX_KIND, INBOX_STATE, inboxTitle, LOADING, SELF_NOTE } from "./text";
import { todayApi, type Gen } from "./todayApi";
import css from "./Today.module.css";

function GenVal({ k, v }: { k: keyof Gen; v: unknown }) {
  if (k === "inputs") return <>{`${Array.isArray(v) ? v.length : v}편`}</>;
  if (k === "tool" || k === "model") return <code>{String(v)}</code>;
  const m = GEN_VALUE[k]?.[String(v)];
  return m ? <>{m}</> : <>기타 <span className="tech">{String(v)}</span></>;
}

type Props = { ctx: UiCtx; id: string; say: (t: string, bad?: boolean, at?: string) => void };

export function InboxOne({ ctx, id, say }: Props) {
  const S = ctx.state!;
  const q = useQuery({ queryKey: ["inbox", "one", id], queryFn: () => todayApi.one(id) });
  const [busy, setBusy] = useState(false), [err, setErr] = useState("");
  if (q.isError) return <LoadFail err={apiErr(q.error)} what="저장 승인 대기 글" />;
  if (!q.data) return <p className="hint">{LOADING}</p>;
  const e = q.data, g = e.generation;
  const to = "#_today";
  async function act(call: () => Promise<unknown>, done: string) {
    setErr(""); setBusy(true);
    try {
      await call();
    } catch (x) {
      const r = apiErr(x);
      setBusy(false);
      if (RELOAD.has(r.code)) { say(postMsg(r), true); await ctx.reload(); } else setErr(postMsg(r));
      return;
    }
    setBusy(false);
    say(done, false, to);
    location.replace(to);
    await ctx.reload();
  }
  const approve = () => act(() => todayApi.approve(e.id), "승인했어요. 내 글로 저장했어요.");
  const exclude = () => { if (window.confirm("이 글을 제외할까요? 대기 본문이 지워지고 되돌릴 수 없어요.")) void act(() => todayApi.exclude(e.id), "제외했어요. 대기 본문을 지웠어요."); };
  const made = e.source_created_at ? mdhm(e.source_created_at) : e.source_date ? dOnly(e.source_date) : "";
  const why = e.is_latest === false ? "더 새 개정이 들어와서 이 개정은 승인할 수 없어요. 최신 개정을 열어 승인하세요." : "지금은 승인할 수 없어요(만료됐거나 이미 처리됐어요).";
  return (
    <div className={css.one}>
      <div className="labels"><span className={`chip${e.kind === "self_summary" ? " o-ai" : ""}`}>{INBOX_KIND[e.kind] || e.kind}</span><span className="chip">{INBOX_STATE[e.state] || e.state}</span></div>
      <h2 className="title">{inboxTitle(S, e)}</h2>
      <dl className="kv"><dt>보낸 장치</dt><dd>{e.device ? e.device.label : "—"}</dd><dt>받은 때</dt><dd>{mdhm(e.received_at)}</dd>
        {e.state === "pending" && e.expires_at ? <><dt>만료 예정</dt><dd>{mdhm(e.expires_at)}</dd></> : null}
        {made ? <><dt>원래 쓴 때</dt><dd>{made}</dd></> : null}<dt>실행</dt><dd>{e.execution === "unattended" ? "무인 실행(PC가 켜져 있을 때 자동)" : "사람이 실행"}</dd>
        {typeof e.activity_ref === "string" && e.activity_ref ? <><dt>붙을 활동</dt><dd><a href={`#_obj/activity/${e.activity_ref}`}>활동 열기</a></dd></> : null}</dl>
      {g && typeof g === "object" ? <><h2 className="sh">AI 생성 정보</h2>
        <dl className="kv">{GEN_LABEL.filter(([k]) => g[k] != null && g[k] !== "").map(([k, l]) => <Fragment key={k}><dt>{l}</dt><dd><GenVal k={k} v={g[k]} /></dd></Fragment>)}</dl>
        <p className="hint">도구·모델 정보는 연결 장치가 신고한 정보예요.</p></> : null}
      <h2 className="sh">본문</h2>
      {e.body != null ? <div className="doc"><p className="pre">{rich(e.body)}</p></div> : <div className="empty">대기 본문이 없어요. 승인·제외·만료 때 대기 본문을 지워요.</div>}
      {e.target_record_id ? <p><a className="link" href={`#_me/journal/${e.target_record_id}`}>저장된 글 열기</a></p> : null}
      {e.state === "pending" ? <>
        <p className="fnote">{e.approve_notice || SELF_NOTE}</p>{e.approvable ? null : <p className="hint">{why}</p>}
        <div className="frow"><button className="primary" type="button" disabled={busy || !e.approvable} onClick={approve}>승인</button>
          <button className="secondary" type="button" disabled={busy} onClick={exclude}>제외</button></div></> : null}
      <p className="ferr" role="alert" aria-atomic="true">{err}</p>
    </div>
  );
}
