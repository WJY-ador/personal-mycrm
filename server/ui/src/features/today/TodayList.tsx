// 「오늘」 목록(옛 todayListSection·todayListHtml·todayRowHtml) — 들어온 날 머리글로 묶는다. 머리글당 활동은 5줄 + 「더 N」(그 날 활동만 펼침, 쓰기 없음) — 대기·저장된 글은 전부
import { useState } from "react";
import { dOnly } from "../../shared/date";
import { kstToday, type Row } from "./rows";
import { ME_EMPTY, SHOW } from "./text";
import css from "./Today.module.css";

export const nav = { fromList: false };   // 1열 — 목록에서 상세로 왔으면 「목록」 = 뒤로 가기

function Day({ day, rows, sel }: { day: string; rows: Row[]; sel: string }) {
  const [open, setOpen] = useState(false);
  const acts = rows.filter(r => r.act), all = open || acts.length <= SHOW;
  const hide = new Set(all ? [] : acts.slice(SHOW).map(r => r.key));
  return (
    <>
      <h3 className={css.day}>{day === kstToday() ? `오늘, ${dOnly(day)}` : dOnly(day) || "날짜 미확인"}</h3>
      <ul className="hrows">{rows.filter(r => !hide.has(r.key)).map(r => (
        <li key={r.key}><a href={r.href} aria-current={r.key === sel ? "true" : undefined} onClick={() => { nav.fromList = true; }}>
          <span className="ht"><span className={`chip ${css.tst} ${r.st === "대기" ? css.wait : css.kept}`}>{r.st}</span>{" "}
            <span className={`chip${r.ai ? " o-ai" : ""}`}>{r.kind}</span> {r.title}</span>
          <span className="hk">{r.meta.filter(Boolean).join(", ")}</span></a></li>
      ))}</ul>
      {all ? null : <button className="tertiary mmore" type="button" onClick={() => setOpen(true)}>{`더 ${hide.size}`}</button>}
    </>
  );
}

export function TodayList({ rows, sel }: { rows: Row[]; sel: string }) {
  if (!rows.length) return <div className="empty">{ME_EMPTY}</div>;
  const days: { day: string; rows: Row[] }[] = [];
  for (const r of rows) { if (!days.length || days[days.length - 1].day !== r.day) days.push({ day: r.day, rows: [] }); days[days.length - 1].rows.push(r); }
  return <>{days.map(d => <Day key={d.day} day={d.day} rows={d.rows} sel={sel} />)}</>;
}
