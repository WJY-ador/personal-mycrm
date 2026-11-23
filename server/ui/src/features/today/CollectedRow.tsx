// 수집 글 줄 하나(로컬 보드의 두 칸 배치를 따른 촘촘한 줄) — 첫 줄 = 작성자, 채널 칩, 축 코드 칩(코드를 모르면 이름), 게시일,
// 둘째 줄 = 한 줄(AI 요약이면 AI 표시, 없으면 제목 줄), 오른쪽 [보관] [버림] [원문 링크]. 줄 버튼과 판별 버튼은 형제(버튼 안에 버튼 없음).
// 넓은 화면 = 줄을 누르면 읽기 판에 그 글(고른 줄 = aria-current + 왼쪽 막대), 한 칸 = 줄 아래 펼침(Detail, 읽기 판과 같은 부품).
// 남의 글이라 명조(--prose)를 쓰지 않는다.
import { useState } from "react";
import { AxisCodes } from "../../shared/AxisCodes";
import { axisCodes } from "../../shared/axes";
import { dOnly } from "../../shared/date";
import { AI_MARK, CHANNEL, NO_BODY, safeUrl } from "./collectedRows";
import type { Post } from "./collectedApi";
import { READER_ID } from "./follow";
import css from "./Collected.module.css";

export type By = Record<string, { code: string | null; title: string }>;
export type RowCtx = { by: By; busy: boolean; wide: boolean; sel: string | null; choose: (id: string) => void; decide: (p: Post, state: string) => Promise<void> };

const AiTag = () => <span className={`chip o-ai ${css.aitag}`}>{AI_MARK}</span>;

// 제목 줄, AI 요약 넷(as-is, to-be, 운영, 요점), 원문 본문은 서버에 없다는 한 줄 — 줄 아래 펼침과 읽기 판이 같이 쓴다
export function Detail({ p, id }: { p: Post; id?: string }) {
  const rows: [string, string | null][] = [["as-is", p.ai.as_is], ["to-be", p.ai.to_be], ["운영", p.ai.ops]];
  const pts = (p.ai.points || []).filter(Boolean);
  const any = rows.some(([, v]) => v) || pts.length > 0;
  return (
    <div className={css.detail} id={id}>
      <p className={css.titleLine}>{p.title || "(제목 줄 없음)"}</p>
      {any ? <div className={css.ai}><p className={css.aihead}><AiTag /> AI가 만든 요약이에요. 내 말이나 원문 인용이 아니에요.</p>
        <dl className="kv">{rows.filter(([, v]) => v).map(([k, v]) => <div key={k} className={css.kvrow}><dt>{k}</dt><dd>{v}</dd></div>)}</dl>
        {pts.length ? <><p className={css.sub}>요점</p><ul className={css.points}>{pts.map((x, i) => <li key={i}>{x}</li>)}</ul></> : null}</div> : null}
      <p className="hint">{NO_BODY}</p>
    </div>
  );
}

export function PostHead({ p, by }: { p: Post; by: By }) {
  return (
    <span className={css.top}><b className={css.author}>{p.author_display || "작성자 미확인"}</b>
      {p.channel ? <span className="chip">{CHANNEL[p.channel] || p.channel}</span> : null}
      <AxisCodes codes={axisCodes(p.axes, by)} />
      {p.posted_on ? <span className={css.date}>{dOnly(p.posted_on)} 게시</span> : null}</span>
  );
}

// [보관](보관함 글이면 없음) [버림] [원문 링크](https 일 때만) — 줄과 읽기 판이 같이 쓴다
export function PostActs({ p, busy, act }: { p: Post; busy: boolean; act: (state: string) => void }) {
  const url = safeUrl(p.post_url);
  return (
    <div className={css.acts}>
      {p.state !== "kept" ? <button type="button" className="secondary small" disabled={busy} onClick={() => act("kept")}>보관</button> : null}
      <button type="button" className="tertiary" disabled={busy} onClick={() => act("dropped")}>버림</button>
      {url ? <a className="link" href={url} target="_blank" rel="noopener noreferrer">원문 링크</a> : null}
    </div>
  );
}

export function CollectedRow({ p, c }: { p: Post; c: RowCtx }) {
  const [open, setOpen] = useState(false);
  const on = c.wide && c.sel === p.id, did = `collected-detail-${p.id}`;
  const face = c.wide ? { "aria-current": on ? "true" as const : undefined, "aria-controls": READER_ID, onClick: () => c.choose(p.id) }
    : { "aria-expanded": open, "aria-controls": open ? did : undefined, onClick: () => setOpen(o => !o) };
  return (
    <li className={css.row} data-id={p.id}>
      <button type="button" className={css.face} data-face="" {...face}>
        <PostHead p={p} by={c.by} />
        <span className={css.line}>{p.ai.summary ? <AiTag /> : null}{p.ai.summary || p.title || "(제목 줄 없음)"}</span>
      </button>
      <PostActs p={p} busy={c.busy} act={s => void c.decide(p, s)} />
      {!c.wide && open ? <Detail p={p} id={did} /> : null}
    </li>
  );
}
