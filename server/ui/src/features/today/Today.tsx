// 「오늘」 화면 틀(옛 renderToday2) — 넓은 화면 = 목록 | 상세(대기 하나), 1열 = 목록 또는 상세 하나. 읽기: 대기 목록 · 최근 활동 50 · 상태의 내 글(불러온 범위).
// 상태를 새로 받으면(껍데기 reload) 조회를 다시 받는다. [삭제] 없음 — 동작은 대기 상세의 승인·제외뿐
import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import type { UiCtx } from "../../shared/ctx";
import { useMobile } from "../../shared/mobile";
import { InboxOne } from "./InboxOne";
import { todayRows } from "./rows";
import { LOADING } from "./text";
import { todayApi } from "./todayApi";
import { nav, TodayList } from "./TodayList";
import css from "./Today.module.css";

type Props = { ctx: UiCtx; sel: string; flash: ReactNode; say: (t: string, bad?: boolean, at?: string) => void };

export function Today({ ctx, sel, flash, say }: Props) {
  const S = ctx.state!, mobile = useMobile();
  const pend = useQuery({ queryKey: ["today", "pending"], queryFn: () => todayApi.list("pending") });
  const acts = useQuery({ queryKey: ["today", "acts"], queryFn: todayApi.acts });
  const ready = !pend.isPending && !acts.isPending;
  const n = pend.data?.counts?.pending;
  const list = (
    <section className={`hlist ${css.list}`} id="home-list" aria-labelledby="today-h">
      <div className="htools"><h3 id="today-h">들어온 것</h3>{n == null ? null : <span className="count">대기 {n}</span>}</div>
      {pend.isError || acts.isError ? <p className="ferr" role="alert">들어온 것 일부를 불러오지 못했어요. 새로 고침해 주세요.</p> : null}
      {ready ? <TodayList rows={todayRows(S, pend.data?.entries || [], acts.data?.activities || [])} sel={sel ? "inbox:" + sel : ""} /> : <p className="hint">{LOADING}</p>}
      <p className={`hint ${css.more}`}>PC·연결 장치에서 들어온 내 글과 활동이에요. 지난 승인 대기(승인함·제외함·만료)는 <a href="#_inbox/all">여기</a>에서 봐요.</p>
    </section>
  );
  const back = () => { if (nav.fromList) { nav.fromList = false; history.back(); } else location.hash = "#_today"; };
  const detail = sel ? (
    <section className="paper hdetail" id="home-detail" aria-live="polite">
      {mobile ? <p className="hback"><button className="secondary" type="button" onClick={back}>목록</button></p> : null}
      <InboxOne key={sel} ctx={ctx} id={sel} say={say} /></section>
  ) : mobile ? null : <section className={`paper hdetail ${css.empty}`}><p className="hint">대기 글을 고르면 여기서 승인하거나 제외해요. 승인해야 저장돼요.</p></section>;
  return (
    <>
      <div className="hhead"><h2>오늘</h2>{flash}</div>
      <div className="home today">{!mobile || !sel ? list : null}{detail}</div>
    </>
  );
}
