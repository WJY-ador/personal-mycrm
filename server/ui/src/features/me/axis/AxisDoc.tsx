// 축 화면의 [한 장] — 최신 한 장(GET /api/axes?id=<축 item id> 의 page.body)을 웹 대화 답과 같은 렌더러(md, 껍데기가 넘긴다)로 그린다.
// 머리 한 줄 = AI 초안 표시 + 갱신 시각. 한 장 기록이 없거나(page null) 축이 없으면(NOT-FOUND) = 「아직 한 장이 없어요.」(실패 아님).
// 한 장 첫 줄 「# 코드. 이름 — …」은 렌더러가 제목으로 못 그린다(## · ### 만) — 떼고 화면 머리(축 코드, 이름)를 쓴다.
import type { ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiErr } from "../../../shared/api";
import { axesApi, type AxisSum } from "../../../shared/axes";
import { mdhm } from "../../../shared/date";
import { LoadFail } from "../../../shared/LoadFail";
import { AXIS_TEXT as T, LOADING } from "../text";
import css from "./Axis.module.css";

export type Md = (text: string, key: string) => ReactNode;

// 맨 앞 빈 줄과 「# 」 머리 한 줄을 뗀다(그 밖은 그대로)
export const dropH1 = (s: string) => {
  const ls = String(s || "").split(/\r\n|\r|\n/);
  const i = ls.findIndex(l => l.trim());
  return i >= 0 && /^ {0,3}# /.test(ls[i]) ? ls.slice(i + 1).join("\n").replace(/^\s*\n/, "") : String(s || "");
};

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
  else body = <>
    <p className={css.ai} id="axis-ai">{T.aiMark}{pq.data.updated_at ? <span className={css.when}>{T.updated(mdhm(pq.data.updated_at))}</span> : null}</p>
    <div className={css.doc}>{md(dropH1(pq.data.markdown), "axis-" + a.item_id)}</div>
  </>;
  return (
    <section className={`paper ${css.box}`} aria-labelledby="axis-doc-h" id="axis-doc">
      <div className="htools"><h3 id="axis-doc-h">{T.page}</h3></div>
      {body}
    </section>
  );
}
