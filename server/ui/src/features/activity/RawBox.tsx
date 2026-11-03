// 원문 열기 — 사용자 PC 의 로컬 에이전트(루프백 주소)로 가는 링크만. 서버·이 화면은 원문을 가져오거나 미리 보지 않는다(fetch 없음).
// 휴대폰·태블릿(주 입력이 손가락이거나 모바일 브라우저)은 버튼 대신 안내만 — 원문은 PC 에만 있다. 포트는 이 브라우저에만(localStorage, 이 키 하나).
import { useState } from "react";
import { RAW_LOCAL, RAW_PORT_DEFAULT, RAW_PORT_KEY } from "./text";
import css from "./Activity.module.css";

const isPhone = () => window.matchMedia?.("(pointer: coarse)").matches || !!(navigator as { userAgentData?: { mobile?: boolean } }).userAgentData?.mobile
  || /Android|iPhone|iPad|iPod|Mobile/i.test(navigator.userAgent || "");

function readPort(): number {
  let v: string | null = null;
  try { v = localStorage.getItem(RAW_PORT_KEY); } catch { /* 저장소를 못 쓰는 브라우저 = 기본 포트 */ }
  const n = Number(v);
  return v && Number.isInteger(n) && n >= 1024 && n <= 65535 ? n : RAW_PORT_DEFAULT;
}

export function RawBox({ raw }: { raw: { raw_id: string } | null }) {
  const [port, setPort] = useState(readPort);
  const [draft, setDraft] = useState(String(port));
  const [err, setErr] = useState("");
  const id = raw && /^[0-9a-f]{48}$/.test(raw.raw_id || "") ? raw.raw_id : "";
  if (!id) return <div className="empty">이 활동엔 원문 ID가 없어요.</div>;
  if (isPhone()) return <button type="button" className="secondary" disabled>{RAW_LOCAL}</button>;
  function save(e: React.FormEvent) {
    e.preventDefault();
    const v = Number(draft);
    if (!Number.isInteger(v) || v < 1024 || v > 65535) return setErr("1024~65535 사이 숫자를 적어 주세요.");
    try { localStorage.setItem(RAW_PORT_KEY, String(v)); } catch { return setErr("이 브라우저는 설정을 저장하지 못해요."); }
    setErr("");
    setPort(v);
  }
  return (
    <div className={css.raw}><a className="btn" href={`http://127.0.0.1:${port}/raw/${id}`} target="_blank" rel="noopener noreferrer">원문 열기 · 이 PC</a>
      <p className="hint">{RAW_LOCAL}. 로컬 에이전트가 켜진 PC에서만 열려요. 서버는 원문을 가져오거나 미리 보여 주지 않아요.</p>
      <details><summary>로컬 연결 포트 {port}</summary><form className="fform" noValidate onSubmit={save}>
        <label htmlFor="raw-port">포트</label><div className="frow" style={{ margin: 0 }}>
          <input className="finput" id="raw-port" name="port" type="number" min={1024} max={65535} value={draft} onChange={e => setDraft(e.target.value)} style={{ maxWidth: "9rem" }} />
          <button className="secondary" type="submit">저장</button></div>
        <p className="hint">이 브라우저에만 저장돼요. 로컬 에이전트의 원문 보기 포트와 같게 맞춰요.</p>
        <p className="ferr" role="alert" aria-atomic="true">{err}</p></form></details></div>
  );
}
