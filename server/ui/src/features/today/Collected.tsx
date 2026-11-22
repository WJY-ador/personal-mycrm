// 「오늘」 맨 위 수집 인박스(대시보드.app 오늘 탭과 같은 묶음) — 머리(수집 N건, 신호 M, 등급 없음 K) · 「원문 링크 있는 것만」 ·
// 등급 묶음(신호, 소식, 노이즈, 등급 없음) · 소식, 노이즈 머리 「전부 버림」(두 번 눌러 확정) · 판별 뒤 되돌리기 5초 · 아래 접힌 「보관함 N건」.
// 판별 정본은 서버(state pending → kept|dropped). 수집 글은 남의 글이고 판단 근거가 아니다 — 명조를 쓰지 않는다.
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { apiErr } from "../../shared/api";
import { LoadFail } from "../../shared/LoadFail";
import { axisMap, useAxes } from "../../shared/axes";
import { BULK_GRADES, groups, headline } from "./collectedRows";
import { collectedApi, type Post } from "./collectedApi";
import { CollectedCard } from "./CollectedCard";
import { DigestBox, pickPosts, type Pick } from "./DigestBox";
import { LOADING } from "./text";
import { useCollected } from "./useCollected";
import css from "./Collected.module.css";

type By = ReturnType<typeof axisMap>;   // 축 item id → 코드·이름(축 코드 칩)

function Kept({ n, act, by }: { n: number; act: ReturnType<typeof useCollected>; by: By }) {
  const [open, setOpen] = useState(false);
  const q = useQuery({ queryKey: ["collected", "kept"], queryFn: () => collectedApi.list("kept"), enabled: open });
  const posts = q.data?.posts;
  return (
    <details className={css.kept} open={open} onToggle={e => setOpen((e.currentTarget as HTMLDetailsElement).open)}>
      <summary>{`보관함 ${q.data ? q.data.counts.kept : n}건`}</summary>
      {!open ? null : q.isError && !posts ? <LoadFail err={apiErr(q.error)} what="보관함" /> : !posts ? <p className="hint">{LOADING}</p>
        : !posts.length ? <p className="hint">보관한 수집 글이 없어요.</p>
        : <ul className={css.cards}>{posts.map(p => <CollectedCard key={p.id} p={p} by={by} busy={act.busy} drop={() => void act.decide(p, "dropped")} />)}</ul>}
    </details>
  );
}

function Group({ grade, label, posts, act, by }: { grade: string; label: string; posts: Post[]; act: ReturnType<typeof useCollected>; by: By }) {
  const armed = act.armed === grade;
  return (
    <section className={css.group} aria-label={label}>
      <div className={css.ghead}><h4>{label}</h4><span className="count">{posts.length}</span>
        {BULK_GRADES.has(grade) ? <button type="button" className={armed ? "secondary small" : "tertiary"} disabled={act.busy}
          onClick={() => act.dropAll(grade, posts)}>{armed ? `한 번 더 누르면 ${posts.length}건 버려요` : "전부 버림"}</button> : null}</div>
      <ul className={css.cards}>{posts.map(p => <CollectedCard key={p.id} p={p} by={by} busy={act.busy}
        keep={() => void act.decide(p, "kept")} drop={() => void act.decide(p, "dropped")} />)}</ul>
    </section>
  );
}

export function Collected() {
  const q = useQuery({ queryKey: ["collected", "pending"], queryFn: () => collectedApi.list("pending") });
  const dq = useQuery({ queryKey: ["collected", "digest"], queryFn: collectedApi.digest });   // 판별 뒤 refresh() 가 같이 다시 받는다
  const [linkOnly, setLinkOnly] = useState(false), [pick, setPickRaw] = useState<Pick>(null);
  const act = useCollected();
  const by = axisMap(useAxes().data?.axes);
  const setPick = (p: Pick) => { setPickRaw(p); act.disarm(); };   // 고른 글이 바뀌면 「전부 버림」 확정 대기를 푼다
  const all = q.data?.posts, shown = all && linkOnly ? all.filter(p => !!p.post_url) : all, posts = shown ? pickPosts(shown, dq.data, pick) : undefined;
  return (
    <section className={`paper ${css.box}`} id="collected" aria-labelledby="collected-h">
      <div className={css.head}><h3 id="collected-h">수집 인박스</h3>
        {shown ? <span className={css.headline}>{headline(shown)}</span> : null}
        <label className={css.only}><input type="checkbox" checked={linkOnly} onChange={e => { setLinkOnly(e.target.checked); act.disarm(); }} /> 원문 링크 있는 것만</label></div>
      {q.data?.ready ? <DigestBox d={dq.data} fail={dq.isError} posts={shown} pick={pick} setPick={setPick} /> : null}
      {act.undo ? <p className={`fok ${css.toast}`} role="status">{act.undo.text}{" "}
        <button type="button" className="tertiary" onClick={act.revert}>되돌리기</button></p>
        : <p className="fok" role="status" aria-atomic="true">{act.note}</p>}
      {act.err ? <p className="ferr" role="alert">{act.err}</p> : null}
      {q.isError && !all ? <LoadFail err={apiErr(q.error)} what="수집 인박스" />
        : !q.data || !posts ? <p className="hint">{LOADING}</p>
        : !q.data.ready ? <p className={`hint ${css.empty}`}>수집 글을 담을 자료 종류(key collected_posts)가 아직 없어요. 만들면 PC가 모은 글이 여기에 쌓여요.</p>
        : !posts.length ? <p className={`hint ${css.empty}`}>{pick && all!.length ? "고른 주제나 축에 남은 대기 글이 없어요." : linkOnly && all!.length ? "원문 링크가 있는 새 수집 글이 없어요." : "새로 들어온 수집 글이 없어요. PC가 모은 글이 여기에 쌓여요."}</p>
        : groups(posts).map(g => <Group key={g.grade || "none"} grade={g.grade} label={g.label} posts={g.posts} act={act} by={by} />)}
      {q.data?.ready ? <Kept n={q.data.counts.kept} act={act} by={by} /> : null}
    </section>
  );
}
