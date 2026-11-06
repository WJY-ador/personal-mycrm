// 활동 하나(옛 actDetail) — 행동·날짜·출처·사람·축·승인된 메모·판 이력·원문(PC 링크). [삭제] = 이 원천의 모든 판을 휴지통으로(옛 trashOn 과 같이 휴지통 켜짐 + 새 탐색일 때만)
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { apiErr } from "../../shared/api";
import { actLabel, ROLE_LABEL } from "../../shared/activity";
import { dOnly, md, mdhm } from "../../shared/date";
import { LoadFail } from "../../shared/LoadFail";
import { postMsg, RELOAD } from "../../shared/postErr";
import type { UiCtx } from "../../shared/ctx";
import { actApi } from "./actApi";
import { RawBox } from "./RawBox";
import { LOADING, TRASH_ASK, TRASH_DONE } from "./text";
import css from "./Activity.module.css";

type Props = { ctx: UiCtx; id: string; say: (t: string, bad?: boolean, at?: string) => void };

export function ActDetail({ ctx, id, say }: Props) {
  const S = ctx.state!;
  const q = useQuery({ queryKey: ["activity", "one", id], queryFn: () => actApi.one(id) });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  if (q.isError && !q.data) return <LoadFail err={apiErr(q.error)} what="활동" />;
  if (!q.data) return <p className="hint">{LOADING}</p>;
  const a = q.data, acts = S.activity_ui?.actions, prov = S.activity_ui?.providers || {};
  async function del() {
    if (!window.confirm(TRASH_ASK)) return;
    setErr(""); setBusy(true);
    try {
      await actApi.trash(a.id);
    } catch (x) {
      const e = apiErr(x);
      setBusy(false);
      if (RELOAD.has(e.code)) { say(postMsg(e), true); await ctx.reload(); } else setErr(postMsg(e));   // 옛 trashDel → coreFail
      return;
    }
    say(TRASH_DONE, false, "#_obj/activity");
    location.replace("#_obj/activity");
    await ctx.reload();
  }
  return (
    <>
      {q.isError ? <LoadFail err={apiErr(q.error)} what="활동" /> : null}
      <div className="eyebrow">활동{a.state === "retracted" ? " · 철회됨" : ""}</div><h2 className="title">{actLabel(acts, a.action)}</h2>
      {a.current ? null : <p className="fnote">이 판은 옛 판이에요. {a.current_id ? <a href={`#_obj/activity/${a.current_id}`}>현재 판 보기</a> : "지금 쓰는 판이 없어요."}</p>}
      {S.switches?.trash ? <><div className="hacts" role="group" aria-label="동작"><button className="secondary" type="button" disabled={busy} onClick={del}>삭제</button></div>
        <p className="ferr" role="alert" aria-atomic="true">{err}</p></> : null}
      <dl className="kv"><dt>행동 날짜</dt><dd>{a.occurred_on ? dOnly(a.occurred_on) : "날짜 미확인"}</dd>
        <dt>처음 수집한 날</dt><dd>{a.observed_on ? dOnly(a.observed_on) : "—"}</dd>
        <dt>받은 때</dt><dd>{mdhm(a.received_at)}</dd>
        <dt>출처</dt><dd>{a.source ? <><a href={`#_obj/source/${a.source.id}`}>{a.source.name}</a>{a.source.provider ? ` · ${prov[a.source.provider] || a.source.provider}` : ""}</> : "—"}</dd></dl>
      <h2 className="sh">사람</h2>{a.people?.length ? <div className="labels">{a.people.map(p => <a key={p.id} className="chip axis" href={`#_obj/person/${p.id}`}>{p.alias} · {ROLE_LABEL[p.role || ""] || p.role}</a>)}</div>
        : <div className="empty">연결된 사람이 없어요.</div>}
      <h2 className="sh">축</h2>{a.axes?.length ? <div className="labels">{a.axes.map(x => <a key={x.id} className="chip axis" href={`#_obj/axis/${x.id}`}>{x.title || "(제목 없음)"}</a>)}</div>
        : <div className="empty">축 미분류</div>}
      <h2 className="sh">승인된 메모·반응</h2>{a.memos?.length ? <ul className="mini">{a.memos.map(m => <li key={m.record_id}><a href={`#_me/journal/${m.record_id}`}>{m.title || "(제목 없음)"}</a><span className="tech">{md(m.created)}</span></li>)}</ul>
        : <div className="empty">없어요. PC에서 쓴 메모는 저장 승인 대기에서 승인하면 여기에 붙어요.</div>}
      <h2 className="sh">판 이력</h2>{a.versions?.length ? <ol className={css.vers}>{a.versions.map(v => <li key={v.id}>{v.id === a.id ? <b>지금 보는 판</b> : <a href={`#_obj/activity/${v.id}`}>이 판 보기</a>}
        {` · ${mdhm(v.received_at)} 받음${v.state === "retracted" ? " · 철회" : ""}`}{v.current ? <> <span className="chip st-mine">현재 판</span></> : null}</li>)}</ol>
        : <div className="empty">—</div>}
      <h2 className="sh">원문</h2><RawBox raw={a.raw} />
    </>
  );
}
