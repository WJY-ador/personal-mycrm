// 수집 인박스 읽기 판(넓은 화면 오른쪽 칸, 화면에 붙어 따라오고 칸 안에서 스크롤) — 고른 글의 작성자, 채널, 축, 게시일, [보관] [버림] [원문 링크],
// 제목 줄, AI 요약 넷, 원문 본문 없음 한 줄(줄 아래 펼침과 같은 Detail). 판별하면 Collected 가 같은 묶음의 다음 글로 넘긴다(follow.ts).
// 판별로 판이 비어 누른 버튼이 사라지면 포커스를 판으로 옮긴다(키보드가 길을 잃지 않게).
import { useRef } from "react";
import type { Post } from "./collectedApi";
import { Detail, PostActs, PostHead, type By } from "./CollectedRow";
import { READER_ID } from "./follow";
import css from "./Collected.module.css";

type Props = { p: Post | null; by: By; busy: boolean; decide: (p: Post, state: string) => Promise<void> };

export function Reader({ p, by, busy, decide }: Props) {
  const ref = useRef<HTMLElement>(null);
  const act = async (q: Post, s: string) => {
    await decide(q, s);
    if (document.activeElement === document.body) ref.current?.focus();
  };
  return (
    <aside className={`paper ${css.pane}`} id={READER_ID} aria-label="읽기 판" tabIndex={-1} ref={ref}>
      {!p ? <p className={`hint ${css.paneEmpty}`}>왼쪽에서 글을 누르면 여기에 요약이 보여요.</p> : <>
        <p className={css.paneHead}><PostHead p={p} by={by} /></p>
        <PostActs p={p} busy={busy} act={s => void act(p, s)} />
        <Detail p={p} />
      </>}
    </aside>
  );
}
