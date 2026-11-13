// 설정 「이 PC」(#_setup/pc) — 앱 다리(window.mycrmDesktop.pc)가 주는 한 줄: 상태, 마지막 동기화 시각과 결과(실패면 이유), [지금 동기화].
// 다리가 없으면(브라우저, 0.1.6 이하 앱) 안내와 내려받기 링크만. 장치 목록, 토큰, 허용 규칙은 사용자 화면에 없다(명세 1.2 — 운영 콘솔에서만)
import { useState } from "react";
import type { ScreenProps } from "../../shared/ctx";
import { mdhm } from "../../shared/date";
import { parsePc, pcBridge, quietCall } from "../../shared/desktopPc";
import { useBridge } from "../../shared/useBridge";
import { BAD, DOWNLOAD, LEAD, LOADING, NEVER, NO_APP, PHASE, REPORT_NOTE, SYNC, TITLE, lastLine, why } from "./text";
import css from "./Pc.module.css";

export function PcScreen(_: ScreenProps) {
  const [bridge] = useState(() => pcBridge());   // 마운트 때 한 번 — 다리는 preload 가 창을 열 때 붙인다
  const st = useBridge(bridge, parsePc);
  let row;
  if (!bridge) row = <p className="hint">{NO_APP} <a href="/download" target="_blank" rel="noopener">{DOWNLOAD}</a></p>;
  else if (st === undefined) row = <p className="hint" role="status">{LOADING}</p>;
  else if (st === null) row = <p className="blocked" role="alert">{BAD}</p>;
  else {
    const bad = st.state === "failed" || st.state === "login";
    const last = st.lastSyncAt ? lastLine(mdhm(st.lastSyncAt), st.lastResult !== "failed") : NEVER;
    const reason = st.lastResult === "failed" || st.state === "login" ? why(st.state === "login" ? st.lastCode || "login" : st.lastCode) : "";
    row = (
      <div className={css.row} role="group" aria-label={TITLE}>
        <span className={css.state} data-bad={bad} role="status">{PHASE[st.state]}</span>
        <span className={css.line}>{last}{reason ? `. ${reason}.` : ""}</span>
        <button type="button" className="secondary" disabled={st.state === "syncing" || !st.signedIn} onClick={() => quietCall(() => bridge.sync())}>{SYNC}</button>
      </div>
    );
  }
  return (
    <div className="paper sheet"><h2 className="title">{TITLE}</h2>
      <p className="hint">{LEAD}</p>
      {row}
      <p className="hint">{REPORT_NOTE}</p>
    </div>
  );
}
