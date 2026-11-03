// 「활동 현황」 접힘(기본 접힘) — 열 때 그 기간 집계를 받는다(30일은 /api/state 에 이미 있다). 열림·기간은 화면(ActivityScreen)이 기억한다
import { useQuery } from "@tanstack/react-query";
import { apiErr } from "../../shared/api";
import { LoadFail } from "../../shared/LoadFail";
import { FIXHINT, Tech } from "../../shared/Tech";
import { readOk, type AppState } from "../../shared/state";
import { actApi } from "./actApi";
import { AggBody } from "./AggBody";
import { LOADING, ME_NOTICE, PERIODS } from "./text";
import css from "./Activity.module.css";

export type Fold = { open: boolean; period: string };
type Props = { S: AppState; fold: Fold; setFold: (f: Fold) => void };

export function AggFold({ S, fold, setFold }: Props) {
  const ok = readOk(S, "activity");
  const mine = fold.period === "30d" && S.activity;
  const q = useQuery({ queryKey: ["activity", "agg", fold.period], queryFn: () => actApi.agg(fold.period), enabled: fold.open && ok && !mine });
  const g = mine ? S.activity : q.data;
  let body;
  if (!ok) body = (   // 옛 partFail — /api/state 의 활동 부분만 못 읽음
    <div className="paper"><div className="partfail" role="alert"><b>활동 집계를 읽지 못했어요 · 나머지는 정상</b>
      <p>{S.read?.activity?.error?.code === "OFFLINE" ? "서버에 연결하지 못했어요." : "읽는 중에 문제가 생겼어요."} {FIXHINT}</p>
      <Tech err={S.read?.activity?.error || { code: "", msg: "" }} /></div></div>
  );
  else body = (
    <div>
      <div className={`pills ${css.periods}`} role="group" aria-label="기간">{PERIODS.map(([k, l]) => (
        <button key={k} type="button" className={k === fold.period ? "on" : ""} aria-pressed={k === fold.period} onClick={() => setFold({ ...fold, period: k })}>{l}</button>
      ))}</div>
      <div>{g ? <AggBody g={g} S={S} /> : q.isError ? <LoadFail err={apiErr(q.error)} what="활동 집계" /> : <p className="hint">{LOADING}</p>}</div>
    </div>
  );
  return (
    <details className="fold" open={fold.open} onToggle={e => { const o = (e.currentTarget as HTMLDetailsElement).open; if (o !== fold.open) setFold({ ...fold, open: o }); }}>
      <summary>활동 현황</summary>
      <p className={`hint ${css.note}`}>{S.activity?.notice || ME_NOTICE}</p>{body}
    </details>
  );
}
