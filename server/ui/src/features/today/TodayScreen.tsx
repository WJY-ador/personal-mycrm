// 「오늘」(옛 renderToday2) · 저장 승인 대기 목록(옛 renderInbox) — 들어온 것을 한 화면 묶음으로. ctx.args = ["today", a, b] | ["inbox", 상태].
// #_today · #_today/inbox/<접수 id>(대기 하나 — 승인·제외) · #_inbox/<상태>(지난 승인 대기). 대기 하나 상세(InboxOne)를 둘이 같이 쓴다.
import { useLayoutEffect } from "react";
import type { ScreenProps } from "../../shared/ctx";
import { Flash, useFlash } from "../../shared/Flash";
import { InboxList } from "./InboxList";
import { Today } from "./Today";

export function TodayScreen({ ctx }: ScreenProps) {
  const { msg, say } = useFlash(ctx);
  const S = ctx.state!, [view = "today", a = "", b = ""] = ctx.args || [];
  const bad = view === "today" && !!a && a !== "inbox";
  useLayoutEffect(() => { if (bad) location.replace("#_today"); }, [bad]);
  if (bad) return null;
  if (view === "inbox") return <InboxList S={S} cur={a || "pending"} flash={<Flash msg={msg} />} />;
  return <Today ctx={ctx} sel={a === "inbox" ? b : ""} flash={<Flash msg={msg} />} say={say} />;
}
