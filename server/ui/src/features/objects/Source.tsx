// 출처 하나(옛 renderSource·srcPanel·sourceCtx) — 이 출처의 내 글(불러온 것만) · 내 요약 · 내 반응 카드 · 이 출처의 활동 · 읽고 든 생각 쓰기 폼
import { useQuery } from "@tanstack/react-query";
import { ActRows } from "../../shared/ActRows";
import { apiErr } from "../../shared/api";
import { Bars } from "../../shared/Bars";
import { Crumbs } from "../../shared/Crumbs";
import { md } from "../../shared/date";
import { LoadFail } from "../../shared/LoadFail";
import { readOk, type AppState } from "../../shared/state";
import { srcById } from "./model";
import { objApi } from "./objApi";
import type { P } from "./props";
import { ReflCards } from "./ReflCard";
import { ReflForm } from "./ReflForm";
import { HOME, LOADING, REFL_KIND, SRC_KIND } from "./text";
import css from "./Objects.module.css";

function Recs({ S, sid }: { S: AppState; sid: string }) {
  const err = S.read?.journal?.error;
  if (!readOk(S, "journal")) return <LoadFail err={{ code: err?.code || "", msg: err?.msg || "" }} what="내 글 목록" />;
  const recs = (S.journal || []).filter(j => j.source_id === sid), total = S.source_counts?.by_source?.[sid] || 0;
  if (!recs.length) return <div className="empty">{total ? `불러온 글 중엔 이 출처의 글이 없어요(모두 ${total}편).` : "이 출처의 글이 없어요."}</div>;
  return (
    <><ul className="mini">{recs.map(j => <li key={j.id}><a href={`#_me/journal/${j.id}`}>{j.title || j.excerpt || "(제목 없음)"}</a><span className="tech">{md(j.created)}</span></li>)}</ul>
      {total > recs.length ? <p className="hint">{`불러온 글만 보여요. 이 출처의 글은 모두 ${total}편이에요.`}</p> : null}</>
  );
}

function Acts({ S, sid }: { S: AppState; sid: string }) {
  const q = useQuery({ queryKey: ["objects", "source", sid], queryFn: () => objApi.source(sid) });
  if (q.isError) return <LoadFail err={apiErr(q.error)} what="이 출처의 활동" />;
  if (!q.data) return <p className="hint">{LOADING}</p>;
  const j = q.data, xs = j.activities || [];
  return (
    <><div className="sechead"><h3>이 출처의 활동 <span className="speclabel">{j.activity_count}</span></h3></div>
      {!j.activity_count ? <div className="empty">이 출처의 활동이 없어요.</div> : <>
        <Bars rows={(j.by_action || []).map(x => ({ label: x.label || S.activity_ui?.actions?.[x.action] || x.action, n: x.n }))} empty="" />
        <ActRows xs={xs} actions={S.activity_ui?.actions} />
        {j.activity_count > xs.length ? <p className="hint">{`최근 ${xs.length}건만 보여요. `}<a href={`#_obj/activity/list/source=${encodeURIComponent(sid)}`}>모두 보기</a></p> : null}</>}</>
  );
}

export function Source(p: P & { id: string }) {
  const { S, msg, id } = p, x = srcById(S, id);
  if (!x) return <div className="paper"><Crumbs xs={[HOME, ["#_obj/source", "출처"]]} />{msg}<div className="empty">찾을 수 없는 출처예요.</div></div>;
  const totalRecs = S.source_counts?.by_source?.[x.id] || 0;
  const rs = (S.reflections || []).filter(r => r.source_id === x.id);
  const col = (k: string) => { const xs = rs.filter(r => r.kind === k);
    return <section><h2 className="sh">{REFL_KIND[k]} <span className="speclabel">{xs.length}</span></h2>{xs.length ? <ReflCards {...p} xs={xs} compact /> : <div className="empty">아직 없어요.</div>}</section>; };
  return (
    <>
      <div className="paper"><Crumbs xs={[HOME, ["#_obj/source", "출처"], ["", x.name]]} />{msg}
        <div className="eyebrow">출처 · {SRC_KIND[x.kind] || x.kind}</div><h2 className="title">{x.name}</h2>
        {x.location ? <p className="recmeta">{x.location}</p> : null}
        <div className={css.cols}>
          <section><h2 className="sh">내 글 <span className="speclabel">{totalRecs}</span></h2><Recs S={S} sid={x.id} /></section>
          {col("summary")}{col("reaction")}
        </div></div>
      <div className="paper"><Acts S={S} sid={x.id} /></div>
      <div className="paper sheet"><h2 className="sh">읽고 든 생각 쓰기</h2><ReflForm {...p} sid={x.id} /></div>
    </>
  );
}
