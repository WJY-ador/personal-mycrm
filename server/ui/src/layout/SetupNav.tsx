// Setup 페이지 줄(옛 subnav·setupNav) — 껍데기 #subnav 자리. 관리자면 운영 관리·운영 콘솔 링크(서버 /admin 이 권한을 지킨다)
// 2026-11-23 이 PC, 문의 및 개인정보만 늘 보이고 나머지 쪽은 접힌 구역 "고급 설정" 안. 지금 쪽이 고급 설정 안이면 펼친다(판정 = shared/route isSetupAdvanced)
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { isSetupAdvanced, setupPages } from "../shared/route";
import type { AppState } from "../shared/state";

export function SetupNav({ S, cur }: { S: AppState; cur: string | null }) {
  const n = document.getElementById("subnav");
  const adv = cur != null && isSetupAdvanced(cur);
  const [open, setOpen] = useState(adv);
  useEffect(() => { if (adv) setOpen(true); }, [adv, cur]);   // 고급 설정 쪽으로 들어오면 펼친다. 접는 것은 사용자만
  useEffect(() => {
    if (!n) return;
    n.hidden = cur == null;
    if (cur == null) n.removeAttribute("aria-label"); else n.setAttribute("aria-label", "설정");
  }, [n, cur]);
  if (!n || cur == null) return null;
  const pages = setupPages(S);
  const link = ([p, l]: [string, string]) =>
    <a key={p} href={`#_setup/${p}`} className={p === cur ? "on" : ""} aria-current={p === cur ? "page" : undefined}>{l}</a>;
  return createPortal(
    <div className="wrap">{pages.filter(p => !isSetupAdvanced(p[0])).map(link)}
      <details className="setup-adv" open={open} onToggle={e => setOpen(e.currentTarget.open)}>
        <summary>고급 설정</summary>
        <div>{pages.filter(p => isSetupAdvanced(p[0])).map(link)}</div>
      </details>
      {S.user?.admin ? <><a href="/admin/setup">운영 관리</a><a href="/admin">운영 콘솔</a></> : null}</div>, n);
}
