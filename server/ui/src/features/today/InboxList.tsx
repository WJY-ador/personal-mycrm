// 저장 승인 대기 목록(옛 renderInbox·inboxRow) — #_inbox/<상태>. 상태 알약(대기 = 「오늘」) · 줄 = 종류·제목 + 장치·받은 때·만료·실행·상태·더 새 개정. [더 보기] = 서버 커서
import { useInfiniteQuery } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { apiErr } from "../../shared/api";
import { Crumbs } from "../../shared/Crumbs";
import { md, mdhm } from "../../shared/date";
import { LoadFail } from "../../shared/LoadFail";
import type { AppState } from "../../shared/state";
import { INBOX_KIND, INBOX_STATE, inboxTitle, LOADING } from "./text";
import { todayApi, type Entry } from "./todayApi";

function Row({ S, e }: { S: AppState; e: Entry }) {
  const meta = [e.device ? e.device.label : "", `${mdhm(e.received_at)} 받음`, e.state === "pending" && e.expires_at ? `${md(e.expires_at)} 만료 예정` : "",
    e.execution === "unattended" ? "무인 실행" : "", e.state !== "pending" ? INBOX_STATE[e.state] || e.state : "", e.state === "pending" && e.is_latest === false ? "더 새 개정 있음" : ""].filter(Boolean).join(", ");
  return (
    <li className="inrow"><a href={`#_inbox/${e.id}`}><span className={`chip${e.kind === "self_summary" ? " o-ai" : ""}`}>{INBOX_KIND[e.kind] || e.kind}</span>
      <b>{inboxTitle(S, e)}</b></a><span className="meta">{meta}</span></li>
  );
}

export function InboxList({ S, cur, flash }: { S: AppState; cur: string; flash: ReactNode }) {
  const st = INBOX_STATE[cur] ? cur : "pending";
  const list = useInfiniteQuery({
    queryKey: ["inbox", "list", st],
    queryFn: ({ pageParam }) => todayApi.list(st, pageParam),
    initialPageParam: "",
    getNextPageParam: last => last.next_cursor || undefined,
  });
  const [moreErr, setMoreErr] = useState("");
  async function more() {
    setMoreErr("");
    const r = await list.fetchNextPage();
    if (r.isFetchNextPageError) setMoreErr("더 불러오지 못했어요. 다시 눌러 주세요.");
  }
  const rows = list.data?.pages.flatMap(x => x.entries);
  return (
    <div className="paper sheet"><Crumbs xs={[["#_today", "오늘"], ["", "저장 승인 대기"]]} />{flash}
      <h2 className="title">저장 승인 대기</h2>
      <p className="hint">{`승인해야 저장돼요. 대기 본문은 ${S.activity_ui?.pending_days || 30}일 보관하고, 승인, 제외, 만료 때 지워요.`}</p>
      <nav className="pills" aria-label="상태">{Object.entries(INBOX_STATE).map(([k, l]) => (
        <a key={k} href={`#_inbox${k === "pending" ? "" : "/" + k}`} className={k === st ? "on" : ""} aria-current={k === st ? "true" : undefined}>
          {l}{k === "pending" && S.inbox ? <span className="n">{S.inbox.pending}</span> : null}</a>
      ))}</nav>
      <div>{list.isError && !list.isFetchNextPageError && !rows ? <LoadFail err={apiErr(list.error)} what="저장 승인 대기" />
        : !rows ? <p className="hint">{LOADING}</p>
        : !rows.length ? <div className="empty">{st === "pending" ? "승인할 글이 없어요." : "없어요."}</div>
        : <>{list.isError && !list.isFetchNextPageError ? <LoadFail err={apiErr(list.error)} what="저장 승인 대기" /> : null}
          <ul className="rows">{rows.map(e => <Row key={e.id} S={S} e={e} />)}</ul>
          {list.hasNextPage ? <button type="button" className="secondary more" disabled={list.isFetchingNextPage} onClick={more}>더 보기</button> : null}
          {moreErr ? <p className="ferr" role="alert">{moreErr}</p> : null}</>}</div>
    </div>
  );
}
