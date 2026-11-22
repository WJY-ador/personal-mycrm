// 축 화면의 [한 장] — 최신 한 장(GET /api/axes?id=<축 item id> 의 page.body, 내 판이 있으면 내 판)을 웹 대화 답과 같은 렌더러(md, 껍데기가 넘긴다)로 그린다.
// 머리 한 줄 = 내 판이면 「내가 고친 판 · 시각」, 아니면 AI 초안 표시 + 갱신 시각. 내 판보다 늦은 AI 초안이 있으면 그 아래 접힌 한 줄(누르면 AI 초안 펼침).
// 본문 두 번 누르기(또는 본문에 포커스 뒤 Enter) = 그 자리 편집(AxisEdit). 한 장 기록이 없거나(page null) 축이 없으면(NOT-FOUND) = 「아직 한 장이 없어요.」(실패 아님).
// 한 장 첫 줄 「# 코드. 이름 — …」은 렌더러가 제목으로 못 그린다(## · ### 만) — 떼고 화면 머리(축 코드, 이름)를 쓴다. 사례 절은 짝 지어 그린다(AxisBody).
import { useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiErr } from "../../../shared/api";
import { axesApi, type AxisPage, type AxisSum } from "../../../shared/axes";
import { mdhm } from "../../../shared/date";
import { LoadFail } from "../../../shared/LoadFail";
import { AXIS_TEXT as T, LOADING } from "../text";
import { AxisBody } from "./AxisBody";
import { AxisEdit } from "./AxisEdit";
import css from "./Axis.module.css";

export type Md = (text: string, key: string) => ReactNode;

// 맨 앞 빈 줄과 「# 」 머리 한 줄을 뗀다(그 밖은 그대로)
export const dropH1 = (s: string) => {
  const ls = String(s || "").split(/\r\n|\r|\n/);
  const i = ls.findIndex(l => l.trim());
  return i >= 0 && /^ {0,3}# /.test(ls[i]) ? ls.slice(i + 1).join("\n").replace(/^\s*\n/, "") : String(s || "");
};

function Head({ p }: { p: AxisPage }) {
  return p.mine
    ? <p className={css.mine} id="axis-mine">{T.mineMark}<span className={css.when}>{mdhm(p.mine.updated_at)}</span></p>
    : <p className={css.ai} id="axis-ai">{T.aiMark}{p.updated_at ? <span className={css.when}>{T.updated(mdhm(p.updated_at))}</span> : null}</p>;
}

// 내 판보다 늦게 온 AI 초안 — 접힌 한 줄(버튼 아님, 제목 줄 누르기로 펼침)
function Newer({ p, md, k }: { p: AxisPage; md: Md; k: string }) {
  if (!p.mine || !p.ai_newer) return null;
  return (
    <details className={css.newer} id="axis-newer">
      <summary>{T.aiNewer(p.ai?.at ? mdhm(p.ai.at) : "")}</summary>
      {p.ai ? <><p className={css.ai}>{T.aiMark}</p><div className={css.doc}><AxisBody markdown={p.ai.markdown} md={md} k={k + "-ai"} /></div></>
        : <p className="hint">{T.aiNone}</p>}
    </details>
  );
}

function View({ a, p, md }: { a: AxisSum; p: AxisPage; md: Md }) {
  const [editing, setEditing] = useState(false);
  const k = "axis-" + a.item_id;
  if (editing) return <><Head p={p} /><AxisEdit itemId={a.item_id} orig={p.markdown} expected={p.mine?.updated_at ?? null} done={() => setEditing(false)} /></>;
  const start = (e: React.SyntheticEvent) => { if (!(e.target as Element).closest("summary, a")) setEditing(true); };
  return <>
    <Head p={p} />
    <Newer p={p} md={md} k={k} />
    <div className={`${css.doc} ${css.editable}`} tabIndex={0} title={T.editTip} aria-describedby="axis-doc-tip" onDoubleClick={start}
      onKeyDown={e => { if (e.key === "Enter" && e.target === e.currentTarget && !e.nativeEvent.isComposing) { e.preventDefault(); setEditing(true); } }}>
      <AxisBody markdown={p.markdown} md={md} k={k} />
    </div>
    <p hidden id="axis-doc-tip">{T.editTip}</p>
  </>;
}

export function AxisDoc({ a, md, fail }: { a: AxisSum | undefined; md: Md; fail: unknown }) {
  const has = !!a?.page;
  const pq = useQuery({ queryKey: ["axes", "page", a?.item_id || "", a?.page?.record_id || "", a?.page?.updated_at || ""],
    queryFn: () => axesApi.page(a!.item_id), enabled: has });
  const gone = pq.isError && apiErr(pq.error).code === "NOT-FOUND";
  let body: ReactNode;
  if (!a) body = fail ? <LoadFail err={apiErr(fail)} what={T.page} /> : <p className="hint">{LOADING}</p>;
  else if (!has || gone || pq.data === null) body = <p className="hint" id="axis-nopage">{T.noPage}</p>;
  else if (pq.isError) body = <LoadFail err={apiErr(pq.error)} what={T.page} />;
  else if (pq.data === undefined) body = <p className="hint">{LOADING}</p>;
  else body = <View a={a} p={pq.data} md={md} />;
  return (
    <section className={`paper ${css.box}`} aria-labelledby="axis-doc-h" id="axis-doc">
      <div className="htools"><h3 id="axis-doc-h">{T.page}</h3></div>
      {body}
    </section>
  );
}
