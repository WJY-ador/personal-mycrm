// 이 PC의 AI 연결(2026-11-13 앱 하나 1.3) — 앱 창에서만(window.mycrmDesktop.ai). 공급자마다 한 줄: 연결됨이면 [연결 끊기], 아니면 [Claude 연결] 하나.
// CLI 가 없는 공급자(missing)는 줄이 없다. 버튼은 바로 끝나고 결과는 다리 상태로 온다 — 바뀌면 서버 선택지(capabilities)도 다시 읽는다.
// 다리가 없으면(브라우저, 옛 앱) 아무것도 그리지 않는다(연결 안내 2단계가 안내한다)
import { useEffect, useRef, useState } from "react";
import { aiBridge, parseAi, quietCall } from "../../shared/desktopPc";
import { useBridge } from "../../shared/useBridge";
import type { WebchatStore } from "./store";
import { AI_CONNECT, AI_DISCONNECT, AI_LINKS, AI_STATE, providerName } from "./text";
import css from "./Webchat.module.css";

export function AiLinks({ s }: { s: WebchatStore }) {
  const [bridge] = useState(() => aiBridge());
  const st = useBridge(bridge, parseAi);
  const seen = useRef("");
  const sig = st ? st.providers.map(p => `${p.provider}:${p.state}`).join(",") : "";
  useEffect(() => {   // 연결 상태가 바뀌면(연결 끝, 끊기) 서버가 아는 선택지를 다시 읽는다. 첫 값은 건너뛴다
    if (!sig) return;
    if (seen.current && seen.current !== sig) void s.loadCapabilities();
    seen.current = sig;
  }, [sig, s]);
  if (!bridge || !st) return null;
  const rows = st.providers.filter(p => p.state !== "missing");
  if (!rows.length) return null;
  return (
    <div className={css.links} role="group" aria-label={AI_LINKS}>
      {rows.map(p => (
        <p key={p.provider} data-ai={p.provider} data-state={p.state}>
          <span>{providerName(p.provider)}, {AI_STATE[p.state]}</span>
          {p.state === "linked" ? <button type="button" className="tertiary" onClick={() => quietCall(() => bridge.disconnect(p.provider))}>{AI_DISCONNECT}</button>
            : p.state === "signed_out" || p.state === "off"
              ? <button type="button" className="primary" onClick={() => quietCall(() => bridge.connect(p.provider))}>{AI_CONNECT(p.provider)}</button> : null}
        </p>
      ))}
    </div>
  );
}
