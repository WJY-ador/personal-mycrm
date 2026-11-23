// 첫 기록 카드(2026-11-23 4차) — 글이 0편일 때 요약 맨 위에 입력칸 하나, [남기기] 하나. 그릴지는 Summary 가 본다(글 0편 또는 방금 여기서 저장함).
// 저장 = [남기기] 또는 Cmd/Ctrl+Enter(한글 조합 중 키는 무시, 빈 글은 안 보냄) → POST /api/records {text}. 저장 중, 오류는 이 카드의 상태다(공용 편집 장치의 run, act 를 쓰지 않는다.
// 나 머리의 이름 편집이 열려 있어도 저장되고, 이름을 눌러도 잠금이 풀리지 않는다). 성공 뒤 다시 받기 = 껍데기 reload 와 같은 모든 조회 무효화.
// 저장 뒤엔 이 화면에 머무는 동안 저장됨 한 줄과 AI 앱 연결 링크(saved 는 Summary 의 컴포넌트 상태). 적은 동안 = 미저장 보호(markDirty).
// 입력칸 id = first-record-input(이름 편집 칸의 hedit-input 과 겹치지 않는다. 그래서 미저장 대화창의 계속 편집은 이 칸으로 포커스를 돌려주지 못한다). 응답을 못 받으면(연결 끊김, 15초) 저장 여부를 모른다고 알린다(다시 누르면 두 번 저장될 수 있다). 브라우저 저장소는 쓰지 않는다
import { useEffect, useRef, useState } from "react";
import { apiErr } from "../../../shared/api";
import { useEdit } from "../../../shared/edit";
import { queryClient } from "../../../shared/queries";
import { postMsg } from "../../../shared/postErr";
import { meApi } from "../meApi";
import css from "./Summary.module.css";

export const FIRST_LABEL = "오늘 있었던 일이나 생각을 한 줄 적어 보세요";
export const FIRST_HELP = "적은 그대로 내 글로 저장돼요.";
export const FIRST_SAVE = "남기기";
export const FIRST_SAVED = "첫 글을 저장했어요. AI 앱을 연결하면 이 글에서 판단을 뽑을 수 있어요.";
export const FIRST_CONNECT = "AI 앱 연결";
export const FIRST_UNKNOWN = "저장됐는지 확인하지 못했어요. 새로 고침해 확인해 주세요.";
const timeout = () => (typeof AbortSignal.timeout === "function" ? AbortSignal.timeout(15000) : undefined);

export function FirstRecord({ saved, onSaved }: { saved: boolean; onSaved: () => void }) {
  const { markDirty } = useEdit();
  const [text, setText] = useState(""), [busy, setBusy] = useState(false), [err, setErr] = useState("");
  const area = useRef<HTMLTextAreaElement>(null), link = useRef<HTMLAnchorElement>(null), sending = useRef(false);
  const empty = !text.trim();
  useEffect(() => { area.current?.focus(); }, []);   // 처음 그려질 때(이름 관문 저장 뒤 첫 화면 포함) 입력칸에
  useEffect(() => { markDirty(!saved && !empty); }, [saved, empty, markDirty]);
  useEffect(() => () => markDirty(false), [markDirty]);
  useEffect(() => { if (saved) link.current?.focus(); }, [saved]);   // 입력칸이 사라지므로 다음 할 일(연결 링크)로

  const save = async () => {
    if (sending.current || saved || busy || !text.trim()) return;   // 연타, 빈 글, 저장 뒤 = 요청 0
    sending.current = true; setBusy(true); setErr("");
    try {
      await meApi.recordAdd(text, timeout());
    } catch (x) {
      const e = apiErr(x);
      if (e.code !== "UNAUTHORIZED") setErr(e.code === "OFFLINE" ? FIRST_UNKNOWN : postMsg(e));
      setBusy(false); sending.current = false;
      return;
    }
    setText(""); onSaved();   // 다시 받기 전에 저장됨으로(글이 생기면 카드 조건이 거짓이 된다)
    try { await queryClient.invalidateQueries(); } finally { setBusy(false); sending.current = false; }
  };
  const key = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.nativeEvent.isComposing) return;
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); void save(); }
  };
  return (
    <section className={css.firstRecord} id="first-record-intro" aria-labelledby={saved ? undefined : "first-record-label"}>
      {!saved && <form className="fform" noValidate onSubmit={e => { e.preventDefault(); void save(); }}>
        <label id="first-record-label" htmlFor="first-record-input">{FIRST_LABEL}</label>
        <textarea ref={area} id="first-record-input" value={text} disabled={busy} aria-describedby="first-record-help first-record-err"
          onChange={e => setText(e.target.value)} onKeyDown={key} />
        <p className="hint" id="first-record-help">{FIRST_HELP}</p>
        <div className="frow"><button className="primary" type="submit" disabled={busy || empty}>{FIRST_SAVE}</button></div>
      </form>}
      <p className="ferr" id="first-record-err" role="alert" aria-atomic="true">{saved ? "" : err}</p>
      <p className="fok" role="status" aria-atomic="true">{saved && <>{FIRST_SAVED} <a ref={link} href="#_setup/connect">{FIRST_CONNECT}</a></>}</p>
    </section>
  );
}
