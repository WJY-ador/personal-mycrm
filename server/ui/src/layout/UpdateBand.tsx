// PC 앱 새 버전 띠(#bands) — 앱 창에서만. 확인 = 마운트 때 · 6시간마다 · 창이 다시 보일 때(마지막 확인에서 1시간 뒤). 겹치지 않는다.
// 판정·출처·나중에 규칙은 shared/desktopUpdate. 내려받기 = 릴리스 페이지 링크(앱 창은 github.com 을 시스템 브라우저로 연다).
import { useEffect, useRef, useState } from "react";
import { CHECK_EVERY_MS, VISIBLE_GAP_MS, fetchLatest, installedVersion, readDismissed, saveDismissed, shouldShow,
  type Dismissed, type Release } from "../shared/desktopUpdate";

export function UpdateBand({ ua = navigator.userAgent }: { ua?: string }) {
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
