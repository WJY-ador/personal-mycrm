// 「나」 축 탭(축 잇기, 2026-11-18 명세 4.1) — #_me/axis = 축 카드 목록, #_me/axis/<축 item id> = 그 축 화면.
// 축 화면 = 머리(코드, 이름, 대기·보관 수) · 접힌 한 줄 「원하는 관점과 키워드」(안 = 키워드 + 기존 항목 상세: 고치기·삭제·연결) ·
// [한 장](AxisDoc) · 그 축의 주제(2026-11-27, 0개면 절 없음) · 그 축의 수집 글(오브젝트 목록 보기에 축 필터, 대기 먼저). 화면에 새 결정(축 고르기·확정) 없음.
import { useState } from "react";
import { apiErr } from "../../../shared/api";
import { axColor, axisHref, COLLECTED_KEY, useAxes, type AxisSum, type AxisTopic } from "../../../shared/axes";
import { dOnly } from "../../../shared/date";
import { LoadFail } from "../../../shared/LoadFail";
import { Back } from "../Back";
import { Detail } from "../Detail";
import type { ObjQuery } from "../meApi";
import { homeRows, type World } from "../model";
import { NO_QUERY } from "../obj/ObjTab";
import { ObjList } from "../obj/ObjList";
import { AXIS_TEXT as T, GONE, LOADING } from "../text";
import { useMobile } from "../view";
import { AxisDoc, type Md } from "./AxisDoc";
import css from "./Axis.module.css";

type Q = ReturnType<typeof useAxes>;
const LIST = "#_me/axis";

function Nums({ a }: { a: AxisSum }) {
  return <span className={css.nums}><span>{T.pending} <b>{a.pending}</b></span><span>{T.kept} <b>{a.kept}</b></span>
    {a.page ? <span className={`chip o-ai ${css.has}`}>{T.hasPage}</span> : null}</span>;
}

function Cards({ q }: { q: Q }) {
  const ax = q.data?.axes;
  return (
    <section className={`paper ${css.box}`} aria-labelledby="axis-list-h" id="axis-list">
      <div className="htools"><h3 id="axis-list-h">{T.list}</h3>{ax ? <span className="count">{ax.length}</span> : null}</div>
      {q.isError && !ax ? <LoadFail err={apiErr(q.error)} what={T.list} /> : !ax ? <p className="hint">{LOADING}</p>
        : !ax.length ? <div className="empty">{T.empty}</div>
        : <ul className={css.cards}>{ax.map((a, i) => <li key={a.item_id}><a href={axisHref(a.item_id)} className={css.card}>
          <span className={css.top}><i className={css.dot} style={{ background: axColor(i) }} /><b className={css.code}>{a.code}</b><span className={css.t}>{a.title}</span></span>
          <Nums a={a} /></a></li>)}</ul>}
    </section>
  );
}

// 축의 주제 — 제목, 글 수, 마지막 날짜. 누르면 주제 항목 페이지(주제 오브젝트 key topics). 서버 순서(마지막 날짜 늦은 순) 그대로
const TOPIC_KEY = "topics";
const TOPICS = { head: "주제", pre: "글", post: "편" };

function Topics({ topics }: { topics: AxisTopic[] }) {
  if (!topics.length) return null;
  return (
    <section className={`paper ${css.box}`} aria-labelledby="axis-topics-h">
      <div className="htools"><h3 id="axis-topics-h">{TOPICS.head}</h3><span className="count">{topics.length}</span></div>
      <ul className={css.cards}>{topics.map(t => <li key={t.item_id}>
        <a href={`#_me/obj/${TOPIC_KEY}/${encodeURIComponent(t.item_id)}`} className={css.card}>
          <span className={css.top}><span className={css.t}>{t.title}</span></span>
          <span className={css.nums}><span>{TOPICS.pre} <b>{t.records}</b>{TOPICS.post}</span>
            {t.last_on ? <span>{dOnly(t.last_on)}</span> : null}</span>
        </a></li>)}</ul>
    </section>
  );
}

function Page({ W, id, q, trashOn, md }: { W: World; id: string; q: Q; trashOn: boolean; md: Md }) {
  const mobile = useMobile();
  const [vq, setVq] = useState<ObjQuery>({ ...NO_QUERY, sort: "state", dir: "desc", axis: id });   // 대기 먼저(pending > kept > dropped)
  const a = q.data?.axes?.find(x => x.item_id === id);
  const r = homeRows(W).find(x => x.k === "item" && x.id === id);
  const def = (W.S.definitions || []).find(d => d.key === COLLECTED_KEY && !d.archived_at);   // 수집 글 오브젝트(없으면 목록 절 없음)
  const back = mobile ? <Back to={LIST} label={T.back} /> : <p className="hback"><a href={LIST}>{T.back}</a></p>;
  if (!a && (!r || r.k !== "item")) return <section className="paper hdetail">{back}
    {q.isPending ? <p className="hint">{LOADING}</p> : <div className="empty">{GONE} <a href={LIST}>{T.back}</a></div>}</section>;
  const code = a?.code || (r?.k === "item" ? r.x.code : "") || "", title = a?.title || r?.title || "";
  return (
    <div className={css.page}>
      <section className={`paper ${css.box}`} aria-labelledby="axis-h">{back}
        <h2 id="axis-h" className={css.h}>{code ? <span className={css.code}>{code}</span> : null}{title}</h2>
        {a ? <Nums a={a} /> : null}
        <details className={css.fold}><summary>{T.fold}</summary>
          {a?.keywords.length ? <p className={css.kw}><span className={css.kl}>{T.keywords}</span>{a.keywords.map(k => <span key={k} className="chip">{k}</span>)}</p> : null}
          {r && r.k === "item" ? <div id="home-detail" className={css.item} aria-live="polite"><Detail W={W} r={r} trashOn={trashOn} /></div>
            : <p className={css.body}>{a?.body || T.noBody}</p>}
        </details>
      </section>
      <AxisDoc a={a} md={md} fail={q.error} />
      {a ? <Topics topics={a.topics} /> : null}
      {def ? <ObjList W={W} def={def} vq={vq} setVq={setVq} hide={["axis"]} /> : null}
    </div>
  );
}

export function AxisTab({ W, id, trashOn, md }: { W: World; id: string; trashOn: boolean; md: Md }) {
  const q = useAxes();
  return id ? <Page key={id} W={W} id={id} q={q} trashOn={trashOn} md={md} /> : <Cards q={q} />;
}
