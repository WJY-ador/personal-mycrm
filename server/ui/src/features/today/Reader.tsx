// 수집 인박스 읽기 판(넓은 화면 오른쪽 칸, 화면에 붙어 따라오고 칸 안에서 스크롤) — 고른 글의 작성자, 채널, 축, 게시일, [보관] [버림] [원문 링크],
// 제목 줄, AI 요약 넷, 원문 본문 없음 한 줄(줄 아래 펼침과 같은 Detail). 판별하면 Collected 가 같은 묶음의 다음 글로 넘긴다(follow.ts).
// 판별로 판이 비어 누른 버튼이 사라지면 포커스를 판으로 옮긴다(키보드가 길을 잃지 않게).
// 2026-11-23 6차: 글은 왼쪽 줄을 여기로 끌어 놓아 연다(줄의 Enter 도 된다). 끄는 동안(dragging) 테두리와 문구로 놓을 자리를 보인다.
// 줄 끌기 자료 종류(DRAG_TYPE)가 있을 때만 놓기를 받는다 — 링크, 글자, 파일을 놓아도 판은 안 바뀐다.
// 2026-11-25: 고른 글에 AI 긴 요약이 없으면 PC 에 만들어 달라고 보내고(useLong) 요약 자리에 상태 한 줄. 실패면 [다시 만들기].
// 상태 줄은 AI 값이 아니라 AI 표시를 붙이지 않는다.
import { useRef, type DragEvent } from "react";
import type { Post } from "./collectedApi";
import { Detail, LongNote, PostActs, PostHead, type By } from "./CollectedRow";
import { DRAG_TYPE, READER_ID } from "./follow";
import { useLong, type Ask } from "./useLong";
import css from "./Collected.module.css";

type Props = { p: Post | null; by: By; busy: boolean; decide: (p: Post, state: string) => Promise<void>;
  dragging: boolean; drop: (id: string) => void; end: () => void; ask: Ask | null; again: (id: string) => void };

const ours = (e: DragEvent) => Array.from(e.dataTransfer?.types || []).includes(DRAG_TYPE);

export function Reader({ p, by, busy, decide, dragging, drop, end, ask, again }: Props) {
  const ref = useRef<HTMLElement>(null);
  const st = useLong(p, ask);
  const act = async (q: Post, s: string) => {
    await decide(q, s);
    if (document.activeElement === document.body) ref.current?.focus();
  };
  const over = (e: DragEvent) => { if (!ours(e)) return; e.preventDefault(); e.dataTransfer.dropEffect = "copy"; };
  const put = (e: DragEvent) => {
    if (!ours(e)) return;
    e.preventDefault();
    const id = e.dataTransfer.getData(DRAG_TYPE);
    end();
    if (id) drop(id);
  };
  return (
    <aside className={`paper ${css.pane}`} id={READER_ID} aria-label="읽기 판" tabIndex={-1} ref={ref}
      data-drop={dragging ? "" : undefined} onDragEnter={over} onDragOver={over} onDrop={put}>
      {dragging ? <p className={`${css.dropHint}${p ? "" : " " + css.paneEmpty}`}>여기에 놓으면 요약이 보여요</p> : null}
      {!p ? (dragging ? null : <p className={`hint ${css.paneEmpty}`}>왼쪽 글을 여기로 끌어 놓으면 요약이 보여요.</p>) : <>
        <p className={css.paneHead}><PostHead p={p} by={by} /></p>
        <PostActs p={p} busy={busy} act={s => void act(p, s)} />
        <Detail p={p} note={<LongNote st={st} again={() => again(p.id)} />} />
      </>}
    </aside>
  );
}
