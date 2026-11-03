// 탭 줄(옛 #nav-tabs) — 「나」 · 「오늘」. 켤 탭 = 라우터 판정(cur) · 오늘 = 저장 승인 대기 수
import type { AppState } from "../shared/state";
import { NAV_TABS } from "../shared/route";

export function Tabs({ S, cur }: { S: AppState; cur: string }) {
  return (
    <>{NAV_TABS.map(t => {
      const on = t.id === cur, n = t.id === "_today" && typeof S.inbox?.pending === "number" ? S.inbox.pending : 0;
      return <a key={t.id} href={`#${t.id}`} className={`tab${on ? " on" : ""}`} aria-current={on ? "page" : undefined}>{t.label}{n ? <span className="n">{n}</span> : null}</a>;
    })}</>
  );
}
