// 활동 목록(옛 renderActivities) — #_obj/activity[/list/<쿼리>] (action·dated·person·source·axis). 사람·출처·축으로 거른 목록엔 현황 접힘을 빼고
// 「…로 거른 목록 · 거르기 풀기」. 거르기(행동·날짜)를 바꾸면 주소로 옮긴다(목록은 주소가 정한다). [더 보기] = 서버 커서
import { useInfiniteQuery } from "@tanstack/react-query";
import { useState } from "react";
import { apiErr } from "../../shared/api";
import { ActRow } from "../../shared/ActRows";
import { LoadFail } from "../../shared/LoadFail";
import type { AppState } from "../../shared/state";
import { actApi } from "./actApi";
import { AggFold, type Fold } from "./AggFold";
import { LIST_HINT, LOADING, MORE_FAIL } from "./text";
import css from "./Activity.module.css";

const KEYS = ["action", "dated", "person", "source", "axis"];

export function ActList({ S, qs, fold, setFold }: { S: AppState; qs: string; fold: Fold; setFold: (f: Fold) => void }) {
  const p = new URLSearchParams(qs || "");
  const q = new URLSearchParams();
  for (const k of KEYS) if (p.get(k)) q.set(k, p.get(k)!);
  const key = q.toString();
  const [moreErr, setMoreErr] = useState("");
  const list = useInfiniteQuery({
    queryKey: ["activity", "list", key],
    queryFn: ({ pageParam }) => actApi.list(key, pageParam),
    initialPageParam: "",
    getNextPageParam: last => last.next_cursor || undefined,
  });
  const person = p.get("person"), source = p.get("source");
  const pa = person ? (S.people || []).find(x => x.id === person) : null, so = source ? (S.sources || []).find(x => x.id === source) : null;
  const by = [person ? (pa ? `사람 ${pa.alias}` : "사람 한 명") : "", source ? `출처 ${so ? so.name : "…"}` : "", p.get("axis") ? "축 하나" : ""].filter(Boolean).join(", ");
  function go(name: string, v: string) {
    const n = new URLSearchParams([...q].filter(([k]) => !["action", "dated"].includes(k)));
    for (const k of ["action", "dated"]) { const val = k === name ? v : p.get(k) || ""; if (val) n.set(k, val); }
    location.hash = n.toString() ? "#_obj/activity/list/" + n.toString() : "#_obj/activity";
  }
  async function more() {
    setMoreErr("");
    const r = await list.fetchNextPage();
    if (r.isFetchNextPageError) setMoreErr(MORE_FAIL);
  }
  const rows = list.data?.pages.flatMap(x => x.activities);
  const opt = (v: string, l: string) => <option key={v} value={v}>{l}</option>;
  return (
    <>
      <h2 className="title">활동</h2>
      <p className="hint">{LIST_HINT}</p>
      {by ? null : <AggFold S={S} fold={fold} setFold={setFold} />}
      <form className={css.filters} onSubmit={e => e.preventDefault()}>
        <label>행동 <select name="action" value={p.get("action") || ""} onChange={e => go("action", e.target.value)}>{opt("", "전부")}
          {Object.entries(S.activity_ui?.actions || {}).map(([k, l]) => opt(k, l))}</select></label>
        <label>날짜 <select name="dated" value={p.get("dated") || ""} onChange={e => go("dated", e.target.value)}>{opt("", "전부")}{opt("yes", "날짜 있음")}{opt("no", "날짜 미확인")}</select></label>
        {by ? <span className="hint">{by}로 거른 목록, <a href="#_obj/activity">거르기 풀기</a></span> : null}
      </form>
      <div>{list.isError && !list.isFetchNextPageError && !rows ? <LoadFail err={apiErr(list.error)} what="활동 목록" />
        : !rows ? <p className="hint">{LOADING}</p>
        : !rows.length ? <div className="empty">아직 활동이 없어요.</div>
        : <>{list.isError && !list.isFetchNextPageError ? <LoadFail err={apiErr(list.error)} what="활동 목록" /> : null}
          <ul className="rows">{rows.map(a => <ActRow key={a.id} a={a} actions={S.activity_ui?.actions} />)}</ul>
          {list.hasNextPage ? <button type="button" className="secondary more" disabled={list.isFetchingNextPage} onClick={more}>더 보기</button> : null}
          {moreErr ? <p className="ferr" role="alert">{moreErr}</p> : null}</>}</div>
    </>
  );
}
