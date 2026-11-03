// Setup 페이지 줄(옛 subnav·setupNav) — 껍데기 #subnav 자리. 관리자면 운영 관리·운영 콘솔 링크(서버 /admin 이 권한을 지킨다)
import { useEffect } from "react";
import { createPortal } from "react-dom";
import { setupPages } from "../shared/route";
import type { AppState } from "../shared/state";

export function SetupNav({ S, cur }: { S: AppState; cur: string | null }) {
  const n = document.getElementById("subnav");
  useEffect(() => {
    if (!n) return;
    n.hidden = cur == null;
    if (cur == null) n.removeAttribute("aria-label"); else n.setAttribute("aria-label", "설정");
  }, [n, cur]);
  if (!n || cur == null) return null;
  return createPortal(
    <div className="wrap">{setupPages(S).map(([p, l]) =>
      <a key={p} href={`#_setup/${p}`} className={p === cur ? "on" : ""} aria-current={p === cur ? "page" : undefined}>{l}</a>)}
      {S.user?.admin ? <><a href="/admin/setup">운영 관리</a><a href="/admin">운영 콘솔</a></> : null}</div>, n);
}
