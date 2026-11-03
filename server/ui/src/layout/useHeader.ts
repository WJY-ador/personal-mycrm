// 머리글·계정 메뉴(옛 acctApply·acct* · data-open 위임 · 로그아웃 · 새로 고침 · 새로 고침 경고). 마크업은 app.html 정적 뼈대 —
// 관리자/사용자 구간(<!--admin-->·<!--user-->)은 서버가 strip 하므로 번들에 그 글자를 두지 않고, 있는 요소만 읽고 묶는다(없으면 건너뛴다).
import { useEffect, useRef, type RefObject } from "react";
import { needName } from "../shared/route";
import type { AppState } from "../shared/state";

type P = { S: AppState | null; reload: () => Promise<unknown>; openName: () => void; openDesk: (where: string) => void; dirty: RefObject<string | null> };
const $ = (id: string) => document.getElementById(id);
const DOW = ["일", "월", "화", "수", "목", "금", "토"];

async function logout() {
  let to = "/?out=1";
  try { const j = await (await fetch("/logout", { method: "POST" })).json(); if (j && j.ok && j.redirect) to = j.redirect; } catch { /* 기본 주소 */ }
  location.href = to;
}

// 상태마다 — 이메일(말줄임, 전체는 title) · 날짜 · 톱니 · 표시 이름 바꾸기 · 저장 승인 대기 (N) · 문의 머리(이름 관문에선 숨김)
function paint(S: AppState) {
  const gate = needName(S), email = S.user?.email || "", who = $("who"), now = new Date();
  if (who) { who.textContent = email; who.title = email; }
  const date = $("date");
  if (date) date.textContent = `${now.getMonth() + 1}월 ${now.getDate()}일 ${DOW[now.getDay()]}요일`;
  const gear = $("setup-link") as HTMLAnchorElement | null;
  if (gear) gear.href = gate && S.user?.admin ? "/admin/setup" : "#_setup";   // 이름 입력 전에도 관리자 운영 경로는 톱니 하나에서
  const name = $("acct-name"), inbox = $("acct-inbox"), n = $("acct-inbox-n"), help = $("acct-help-h");
  if (name) name.hidden = gate || !(S.user && "display_name" in S.user);
  $("acct-menu")?.classList.toggle("navnew", !gate);
  if (inbox) inbox.hidden = gate;
  const inN = typeof S.inbox?.pending === "number" && S.inbox.pending > 0 ? S.inbox.pending : null;
  if (n) n.textContent = inN === null ? "" : ` (${inN})`;
  if (help) help.hidden = gate;
}

export function useHeader(p: P) {
  const ref = useRef(p);
  ref.current = p;
  useEffect(() => { if (p.S) paint(p.S); });
  useEffect(() => {
    const acct = $("acct") as HTMLDetailsElement | null, menu = $("acct-menu"), out = $("logout"), again = $("reload");
    const close = () => { if (acct) acct.open = false; };
    const onMenu = (e: Event) => {
      const b = (e.target as Element).closest<HTMLElement>("button[data-acct]");
      if (!b || !ref.current.S) return;
      const act = b.dataset.acct || "";
      if (act === "logout") return;   // 로그아웃 = #logout
      const go: Record<string, string> = { devices: "#_devices", inbox: "#_inbox", settings: "#_settings/structure" };
      close();
      if (act === "name") ref.current.openName();
      else if (go[act]) location.hash = go[act];
      else if (act === "send" || act === "mine" || act === "privacy") ref.current.openDesk(act);
    };
    // 화면 안의 [data-open](문의 보내기·내 문의·개인정보 요청·로그아웃 — 이름 관문·설정·자료 종류) + 메뉴 밖을 누르면 메뉴 닫기
    const onDoc = (e: Event) => {
      const op = (e.target as Element).closest?.<HTMLElement>("[data-open]");
      if (op) { e.preventDefault(); if (op.dataset.open === "logout") void logout(); else ref.current.openDesk(op.dataset.open || ""); }
      if (acct?.open && !acct.contains(e.target as Node)) close();
    };
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if ((e.key === "Enter" || e.key === " ") && t.matches?.("[data-open]")) { e.preventDefault(); t.click(); }
    };
    const onEsc = (e: KeyboardEvent) => { if (e.key === "Escape" && acct?.open) { close(); acct.querySelector("summary")?.focus(); } };
    const onUnload = (e: BeforeUnloadEvent) => { if (ref.current.dirty.current) { e.preventDefault(); e.returnValue = ""; } };   // 고치던 글 — 새로 고침·닫기
    const onReload = () => void ref.current.reload();
    const onOut = () => void logout();
    menu?.addEventListener("click", onMenu);
    out?.addEventListener("click", onOut);
    again?.addEventListener("click", onReload);
    acct?.addEventListener("keydown", onEsc);
    document.addEventListener("click", onDoc);
    document.addEventListener("keydown", onKey);
    window.addEventListener("beforeunload", onUnload);
    return () => {
      menu?.removeEventListener("click", onMenu);
      out?.removeEventListener("click", onOut);
      again?.removeEventListener("click", onReload);
      acct?.removeEventListener("keydown", onEsc);
      document.removeEventListener("click", onDoc);
      document.removeEventListener("keydown", onKey);
      window.removeEventListener("beforeunload", onUnload);
    };
  }, []);
}
