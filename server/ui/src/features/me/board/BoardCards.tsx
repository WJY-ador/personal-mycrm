// 한판 상세 카드 — 출처 카드(수집 글 | 기록)와 소제목 카드. 카드를 누르면 전문을 펼친다(버튼 하나 = 카드 앞면). 수집 글의 AI 요약은 AI 표시와 문구를 같이.
import { useState, type ReactNode } from "react";
import { mmdd, dOnly } from "../../../shared/date";
import { AI_MARK } from "../../../shared/words";
import type { RoutineRef, RoutineSubhead } from "../meApi";
import css from "./Board.module.css";

export const BT = { back: "루틴판으로", inflow: "들어온 것", decided: "내가 정한 것", out: "이렇게 나왔다", from: (ks: string[]) => `나온 곳: ${ks.join(", ")}`,
  noSrc: "출처 없음", noIn: "들어온 글 없음", noDec: "이어진 결정 없음", noSub: "아직 소제목이 없어요. 대화에서 '루틴 하자'",
  ai: "AI가 만든 요약이에요. 내 말이나 원문 인용이 아니에요.", verdict: (v: string) => `맞았나: ${v}`, untitled: "(제목 없음)",
  missing: (n: number) => `지금 볼 수 없는 출처 ${n}`, fail: "불러오지 못했어요. 새로 고침해 주세요." };

function Face({ open, toggle, k, out, children }: { open: boolean; toggle: () => void; k: string; out?: boolean; children: ReactNode }) {
  return <button type="button" className={css.face} aria-expanded={open} onClick={toggle}>
    <span className={`${css.key}${out ? " " + css.okey : ""}`}>{k}</span><span className={css.sum}>{children}</span></button>;
}

function RefBody({ r }: { r: RoutineRef }) {
  if (r.kind === "post") return <div className={css.body}>
    <p className={css.st}>{r.title || BT.untitled}</p>
    <p className={css.by}>{[r.author, r.channel, dOnly(r.date)].filter(Boolean).join(", ")}</p>
    {r.ai_summary ? <p className={css.ai}><span className="chip o-ai">{AI_MARK}</span> {BT.ai}<br />{r.ai_summary}</p> : null}</div>;
  return <div className={css.body}>
    <p className={css.st}>{r.title || BT.untitled}</p>
    {r.item ? <p className={css.by}>{r.item.title}{r.item.verdict ? `. ${BT.verdict(r.item.verdict)}` : ""}</p> : null}
    {r.date ? <p className={css.by}>{dOnly(r.date)}</p> : null}</div>;
}

export function RefCard({ r, k, on }: { r: RoutineRef; k: string; on: boolean }) {
  const [open, setOpen] = useState(false);
  return <li className={`${css.src}${on ? " " + css.on : ""}`} data-k={k}>
    <Face open={open} toggle={() => setOpen(o => !o)} k={k}><span className={css.dt}>{mmdd(r.date)}</span><span className={css.tl}>{r.title || BT.untitled}</span></Face>
    {open ? <RefBody r={r} /> : null}</li>;
}

type SubProps = { s: RoutineSubhead; o: number; from: string[]; on: boolean; hover: (on: boolean) => void };
export function SubCard({ s, o, from, on, hover }: SubProps) {
  const [open, setOpen] = useState(false);
  const h = (v: boolean) => () => hover(v);
  return <li className={`${css.out}${on ? " " + css.on : ""}${from.length ? "" : " " + css.nosrc}`} data-o={o}
    onMouseEnter={h(true)} onMouseLeave={h(false)} onFocus={h(true)} onBlur={h(false)}>
    <Face open={open} toggle={() => setOpen(x => !x)} k={String(o + 1)} out><span className={css.tl}>{s.text}</span></Face>
    {open && s.body ? <div className={css.body}><p className={`${css.st} ${css.prose}`}>{s.body}</p></div> : null}
    <p className={css.from}>{from.length ? BT.from(from) : BT.noSrc}</p></li>;
}
