// 수집 글 카드 하나 — 작성자 · 채널 칩 · 축 · 한 줄(AI 요약이면 「AI 요약」 표시, 없으면 제목 줄) · 게시일 · [보관]·[버림]·[원문 링크].
// 카드를 누르면 펼침: 제목 줄 · AI 요약 넷(as-is, to-be, 운영, 요점) · 원문 본문은 서버에 없다는 한 줄. 남의 글이라 명조(--prose)를 쓰지 않는다.
import { useState } from "react";
import { dOnly } from "../../shared/date";
import { AI_MARK, CHANNEL, NO_BODY, safeUrl } from "./collectedRows";
import type { Post } from "./collectedApi";
import css from "./Collected.module.css";

const AiTag = () => <span className={`chip o-ai ${css.aitag}`}>{AI_MARK}</span>;

function Detail({ p }: { p: Post }) {
  const rows: [string, string | null][] = [["as-is", p.ai.as_is], ["to-be", p.ai.to_be], ["운영", p.ai.ops]];
  const pts = (p.ai.points || []).filter(Boolean);
  const any = rows.some(([, v]) => v) || pts.length > 0;
  return (
    <div className={css.detail}>
      <p className={css.titleLine}>{p.title || "(제목 줄 없음)"}</p>
      {any ? <div className={css.ai}><p className={css.aihead}><AiTag /> AI가 만든 요약이에요. 내 말이나 원문 인용이 아니에요.</p>
        <dl className="kv">{rows.filter(([, v]) => v).map(([k, v]) => <div key={k} className={css.kvrow}><dt>{k}</dt><dd>{v}</dd></div>)}</dl>
        {pts.length ? <><p className={css.sub}>요점</p><ul className={css.points}>{pts.map((x, i) => <li key={i}>{x}</li>)}</ul></> : null}</div> : null}
      <p className="hint">{NO_BODY}</p>
    </div>
  );
}

type Props = { p: Post; busy: boolean; keep?: () => void; drop: () => void };

export function CollectedCard({ p, busy, keep, drop }: Props) {
  const [open, setOpen] = useState(false);
  const url = safeUrl(p.post_url), line = p.ai.summary || p.title || "(제목 줄 없음)";
  return (
    <li className={css.card} data-id={p.id}>
      <button type="button" className={css.face} aria-expanded={open} onClick={() => setOpen(o => !o)}>
        <span className={css.top}><b className={css.author}>{p.author_display || "작성자 미확인"}</b>
          {p.channel ? <span className="chip">{CHANNEL[p.channel] || p.channel}</span> : null}
          {p.axes.map(a => <span key={a.id} className={`chip ${css.axis}`}>{a.title}</span>)}
          {p.posted_on ? <span className={css.date}>{dOnly(p.posted_on)} 게시</span> : null}</span>
        <span className={css.line}>{p.ai.summary ? <AiTag /> : null}{line}</span>
      </button>
      {open ? <Detail p={p} /> : null}
      <div className={css.acts}>
        {keep ? <button type="button" className="secondary small" disabled={busy} onClick={keep}>보관</button> : null}
        <button type="button" className="tertiary" disabled={busy} onClick={drop}>버림</button>
        {url ? <a className="link" href={url} target="_blank" rel="noopener noreferrer">원문 링크</a> : null}
      </div>
    </li>
  );
}
