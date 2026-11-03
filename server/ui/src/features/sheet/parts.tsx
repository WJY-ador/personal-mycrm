// 질문·기록 탭 조각(옛 sayLine·nextLine·firstRun·evLine·recRow) — 글자 그대로. 원문 열기 = 화면의 원문 대화창(open).
import { useState } from "react";
import { dayParts } from "../../shared/date";
import { press } from "../../shared/press";
import { rich } from "../../shared/rich";
import { recLabel } from "../../shared/RecDialog";
import type { AppState, Cand } from "../../shared/state";

export type Open = (id: string, quote?: string) => void;
const SAY: Record<string, string> = { record: "기록 남기자", digest: "후보 뽑아 줘", question: "질문 하나 남길게", free: "기록 남기자" };

export function SayLine({ phrase }: { phrase: string }) {
  const [done, setDone] = useState(false);
  const copy = () => { navigator.clipboard?.writeText(phrase).then(() => { setDone(true); setTimeout(() => setDone(false), 1500); }, () => {}); };
  return <div className="say">연결한 AI 대화에서 「{phrase}」라고 말하기 <button className="small" type="button" onClick={copy}>{done ? "요청을 복사했어요." : "요청 복사"}</button></div>;
}

export function NextLine({ S }: { S: AppState }) {
  const n = S.next;
  if (!n || typeof n !== "object") return null;
  return (
    <div className="nextline"><span className="lbl">다음 할 일</span><span className="txt">{n.text}</span>
      {n.kind !== "review" && SAY[n.kind] ? <details><summary>어떻게 하나요?</summary><SayLine phrase={SAY[n.kind]} /></details> : null}</div>
  );
}

export function FirstRun({ S }: { S: AppState }) {
  const n = (S.journal || []).length;
  return (
    <div className="first"><h2>최근에 겪은 일을 한 편 적어볼까요?</h2><p>질문은 나중에 정해도 돼요.{n ? ` 지금 내 글이 ${n}편 있어요.` : ""}</p>
      <ol className="steps"><li><b>내 글</b>겪은 일을 내 말로 적어요.</li>
        <li className="cand"><b>검토할 판단</b>내 글에서 판단이 될 만한 문장을 뽑아요. 아직 확정한 판단은 아니에요.</li>
        <li className="mine"><b>확정한 판단</b>원문과 대조해 내가 남긴 문장만 쌓여요.</li></ol>
      <SayLine phrase="기록 남기자" /></div>
  );
}

// 근거 한 줄 — 글 이름(원문 열기) · 인용(굵게)
export function EvLine({ S, c, open }: { S: AppState; c: Cand; open: Open }) {
  return (
    <div className="ev">근거 <a {...press(() => open(c.record_id, c.quote))}>{recLabel(S, c.record_id)}</a>
      {" · "}<q><mark>{rich(c.quote)}</mark></q></div>
  );
}


export function RecRow({ S, id, open }: { S: AppState; id: string; open: Open }) {
  const r = (S.journal || []).find(j => j.id === id), dp = dayParts(r?.created);
  const title = !r ? "찾을 수 없는 글" : r.broken ? "읽지 못한 글" : r.title;
  return (
    <li><a {...press(() => open(id))}>
      <div className="d">{dp.d}<small>{dp.mo ? dp.mo + "월" : ""}</small></div>
      <div><div className="t">{title}</div><div className="s">{r?.excerpt || ""}</div></div></a></li>
  );
}
