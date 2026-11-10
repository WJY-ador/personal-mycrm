// PC 앱 새 버전 띠(#bands) — 앱 창에서만. 다리(window.mycrmDesktop.update)가 있으면 앱이 알려 준 상태만 그린다(BridgeBand).
// 다리가 없는 옛 앱 = 직접 확인(WebBand): 마운트 때 · 6시간마다 · 창이 다시 보일 때(마지막 확인에서 1시간 뒤). 겹치지 않는다.
// 판정·출처·나중에 규칙은 shared/desktopUpdate. 내려받기 = 릴리스 페이지 링크(앱 창은 github.com 을 시스템 브라우저로 연다).
import { useEffect, useRef, useState, type ReactNode } from "react";
import { CHECK_EVERY_MS, SNOOZE_MS, VISIBLE_GAP_MS, desktopBridge, fetchLatest, installedVersion, parseState, readDismissed, releasePage,
  saveDismissed, shouldShow, shouldShowApp, type DesktopUpdate, type Dismissed, type Release, type UpdateState } from "../shared/desktopUpdate";

export function UpdateBand({ ua = navigator.userAgent }: { ua?: string }) {
  const [bridge] = useState(() => desktopBridge());   // 마운트 때 한 번 — 다리는 preload 가 창을 열 때 붙인다
  return bridge ? <BridgeBand bridge={bridge} /> : <WebBand ua={ua} />;
}

function WebBand({ ua }: { ua: string }) {
  const [installed] = useState(() => installedVersion(ua));
  const [rel, setRel] = useState<Release | null>(null);
  const [dismissed, setDismissed] = useState<Dismissed | null>(() => (installed ? readDismissed() : null));
  const busy = useRef(false), last = useRef(0);

  useEffect(() => {
    if (!installed) return;
    const stop = new AbortController();
    const check = async () => {
      if (busy.current) return;
      busy.current = true;
      last.current = Date.now();
      try {
        const r = await fetchLatest(AbortSignal.any([stop.signal, AbortSignal.timeout(15_000)]));
        if (r && !stop.signal.aborted) setRel(r);   // 실패는 띠를 새로 만들지 않는다(앞서 받은 결과는 그대로)
      } finally { busy.current = false; }
    };
    const onVisible = () => { if (document.visibilityState === "visible" && Date.now() - last.current >= VISIBLE_GAP_MS) void check(); };
    void check();
    const timer = window.setInterval(() => void check(), CHECK_EVERY_MS);
    document.addEventListener("visibilitychange", onVisible);
    return () => { stop.abort(); window.clearInterval(timer); document.removeEventListener("visibilitychange", onVisible); };
  }, [installed]);

  if (!rel || !shouldShow(installed, rel, dismissed, Date.now())) return null;
  const later = () => { const d = { version: rel.version, at: Date.now() }; saveDismissed(d); setDismissed(d); };
  return (
    <div className="band update" role="region" aria-label="MyCRM 앱 업데이트">
      <span className="update-text">MyCRM 앱 새 버전이 나왔어요. 지금 v{installed}, 새 버전 {rel.version}.</span>
      <span className="update-acts">
        <a className="btn primary" href={rel.url} target="_blank" rel="noopener noreferrer"
          aria-label={`MyCRM 앱 ${rel.version} 내려받기`}>내려받기</a>
        <button type="button" className="secondary" onClick={later} aria-label="업데이트 안내 나중에 보기">나중에</button>
      </span>
    </div>
  );
}

// 다리 호출이 던지거나 거절해도 화면은 그대로 — 결과는 상태(onChange)로 온다
function quiet(f: () => unknown): void {
  try { void Promise.resolve(f()).catch(() => {}); } catch { /* 다리 오류 — 띠는 다음 상태를 기다린다 */ }
}

function BridgeBand({ bridge }: { bridge: DesktopUpdate }) {
  const [st, setSt] = useState<UpdateState | null>(null);
  const [dismissed, setDismissed] = useState<Dismissed | null>(() => readDismissed());
  const [, tick] = useState(0);

  useEffect(() => {
    let live = true, pushed = false, off: unknown;
    try { off = bridge.onChange(s => { pushed = true; if (live) setSt(parseState(s)); }); } catch { /* 구독 실패 — get 만 쓴다 */ }
    try {
      Promise.resolve(bridge.get()).then(s => { if (live && !pushed) setSt(parseState(s)); }, () => {});   // 먼저 온 알림이 더 새 상태
    } catch { /* 읽기 실패 = 띠 없음 */ }
    return () => { live = false; try { if (typeof off === "function") off(); } catch { /* 해제 실패 — 창이 닫히면 앱이 정리 */ } };
  }, [bridge]);

  useEffect(() => {   // 나중에 24시간이 지나면 상태 알림이 없어도 다시 그린다
    if (!dismissed) return;
    const left = dismissed.at + SNOOZE_MS - Date.now();
    if (left <= 0) return;
    const t = window.setTimeout(() => tick(n => n + 1), left);
    return () => window.clearTimeout(t);
  }, [dismissed]);

  if (!st || !shouldShowApp(st, dismissed, Date.now())) return null;
  const v = `v${st.version}`;
  const later = () => { const d = { version: v, at: Date.now() }; saveDismissed(d); setDismissed(d); };
  const laterBtn = <button type="button" className="secondary" onClick={later} aria-label="업데이트 안내 나중에 보기">나중에</button>;
  const page = (label: string, aria: string, primary: boolean) => (
    <a className={primary ? "btn primary" : "btn"} href={releasePage(st.version)} target="_blank" rel="noopener noreferrer" aria-label={aria}>{label}</a>);
  let text: string, acts: ReactNode = null;
  if (st.phase === "available") {
    text = `MyCRM 앱 새 버전이 나왔어요. 지금 v${st.current}, 새 버전 ${v}.`;
    acts = <>{st.inApp
      ? <button type="button" className="primary" onClick={() => quiet(() => bridge.download())} aria-label={`MyCRM 앱 ${v} 지금 업데이트`}>지금 업데이트</button>
      : page("내려받기", `MyCRM 앱 ${v} 내려받기`, true)}{laterBtn}</>;
  } else if (st.phase === "downloading") {
    text = `새 버전을 받고 있어요.${st.percent === null ? "" : ` ${st.percent}%`}`;
  } else if (st.phase === "downloaded") {
    text = "새 버전을 받았어요. 다시 시작하면 설치돼요.";
    acts = <><button type="button" className="primary" onClick={() => quiet(() => bridge.install())} aria-label={`MyCRM 앱을 다시 시작해 ${v} 설치`}>다시 시작</button>{laterBtn}</>;
  } else {
    text = st.reason === "install" ? "업데이트를 설치하지 못했어요." : "업데이트를 받지 못했어요.";
    acts = <><button type="button" className="primary" onClick={() => quiet(() => bridge.download())} aria-label="업데이트 다시 시도">다시 시도</button>
      {page("직접 내려받기", "릴리스 페이지에서 MyCRM 앱 직접 내려받기", false)}</>;
  }
  return (
    <div className="band update" role="region" aria-label="MyCRM 앱 업데이트">
      <span className="update-text">{text}</span>
      {acts && <span className="update-acts">{acts}</span>}
    </div>
  );
}
