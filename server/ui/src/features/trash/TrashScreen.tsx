// Setup 「휴지통」 — 목록(서버 커서로 [더 보기]) · [복원] · [영구 삭제](확인창). 기한 지난 행은 서버가 목록에서 뺀다.
// 복원·영구 삭제 뒤엔 상태 한 벌을 다시 받는다(ctx.reload — 떠 있는 목록도 같이 다시 받는다).
import { useState } from "react";
import { useInfiniteQuery } from "@tanstack/react-query";
import { apiErr } from "../../shared/api";
import type { ScreenProps } from "../../shared/ctx";
import { trashAct, trashList, type TrashAct, type TrashItem } from "./trashApi";
import { TrashRow } from "./TrashRow";
import { LOADING, MORE_FAIL, TRASH_EMPTY, TRASH_NOTE, TRASH_PURGE_ASK, TRASH_PURGED, TRASH_RESTORED, actErrText, loadErrText } from "./text";
import css from "./Trash.module.css";

export function TrashScreen({ ctx }: ScreenProps) {
  const [msg, setMsg] = useState({ text: "", bad: false });
  const [busy, setBusy] = useState(false);
  const q = useInfiniteQuery({
    queryKey: ["trash"],
    queryFn: ({ pageParam }) => trashList(pageParam),
    initialPageParam: "",
    getNextPageParam: last => last.next_cursor || undefined,
  });

  async function act(a: TrashAct, x: TrashItem) {
    if (a === "purge" && !window.confirm(TRASH_PURGE_ASK)) return;
    setMsg({ text: "", bad: false });
    setBusy(true);
    try {
      await trashAct(a, x.kind, x.id);
      setMsg({ text: a === "purge" ? TRASH_PURGED : TRASH_RESTORED, bad: false });
    } catch (e) {
      setMsg({ text: actErrText(apiErr(e)), bad: true });
    }
    await ctx.reload();
    setBusy(false);
  }

  async function more() {
    const r = await q.fetchNextPage();
    if (r.isFetchNextPageError) setMsg({ text: MORE_FAIL, bad: true });
  }

  const rows = q.data?.pages.flatMap(p => p.items);
  let body;
  if (q.isError && !q.isFetchNextPageError) body = <div className="empty">{loadErrText(apiErr(q.error))}</div>;
  else if (!rows) body = <p className="hint">{LOADING}</p>;
  else if (!rows.length) body = <div className="empty">{TRASH_EMPTY}</div>;
  else body = (
    <>
      <ul className={css.list}>{rows.map(x => <TrashRow key={`${x.kind}:${x.id}`} x={x} busy={busy} onAct={act} />)}</ul>
      {q.hasNextPage && (
        <button className="secondary more" type="button" disabled={q.isFetchingNextPage} onClick={more}>
          {q.isFetchingNextPage ? LOADING : "더 보기"}
        </button>
      )}
    </>
  );
  return (
    <div className="paper sheet">
      <h2 className="title">휴지통</h2>
      <p className="hint">{TRASH_NOTE}</p>
      <p className={msg.bad ? "ferr" : "fok"} id="trash-msg" role="status" aria-atomic="true">{msg.text}</p>
      {body}
    </div>
  );
}
