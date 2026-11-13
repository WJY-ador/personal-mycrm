// 「오늘」 맨 위 수집 인박스(대시보드.app 오늘 탭과 같은 묶음) — 머리(수집 N건, 신호 M, 등급 없음 K) · 「원문 링크 있는 것만」 ·
// 등급 묶음(신호, 소식, 노이즈, 등급 없음) · 소식, 노이즈 머리 「전부 버림」(두 번 눌러 확정) · 판별 뒤 되돌리기 5초 · 아래 접힌 「보관함 N건」.
// 판별 정본은 서버(state pending → kept|dropped). 수집 글은 남의 글이고 판단 근거가 아니다 — 명조를 쓰지 않는다.
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { apiErr } from "../../shared/api";
import { LoadFail } from "../../shared/LoadFail";
import { BULK_GRADES, groups, headline } from "./collectedRows";
import { collectedApi, type Post } from "./collectedApi";
import { CollectedCard } from "./CollectedCard";
import { LOADING } from "./text";
import { useCollected } from "./useCollected";
import css from "./Collected.module.css";

function Kept({ n, act }: { n: number; act: ReturnType<typeof useCollected> }) {
  const [open, setOpen] = useState(false);
  const q = useQuery({ queryKey: ["collected", "kept"], queryFn: () => collectedApi.list("kept"), enabled: open });
  const posts = q.data?.posts;
  return (
    <details className={css.kept} open={open} onToggle={e => setOpen((e.currentTarget as HTMLDetailsElement).open)}>
      <summary>{`보관함 ${q.data ? q.data.counts.kept : n}건`}</summary>
      {!open ? null : q.isError && !posts ? <LoadFail err={apiErr(q.error)} what="보관함" /> : !posts ? <p className="hint">{LOADING}</p>
        : !posts.length ? <p className="hint">보관한 수집 글이 없어요.</p>
        : <ul className={css.cards}>{posts.map(p => <CollectedCard key={p.id} p={p} busy={act.busy} drop={() => void act.decide(p, "dropped")} />)}</ul>}
    </details>
  );
}

function Group({ grade, label, posts, act }: { grade: string; label: string; posts: Post[]; act: ReturnType<typeof useCollected> }) {
  const armed = act.armed === grade;
  return (
    <section className={css.group} aria-label={label}>
      <div className={css.ghead}><h4>{label}</h4><span className="count">{posts.length}</span>
        {BULK_GRADES.has(grade) ? <button type="button" className={armed ? "secondary small" : "tertiary"} disabled={act.busy}
          onClick={() => act.dropAll(grade, posts)}>{armed ? `한 번 더 누르면 ${posts.length}건 버려요` : "전부 버림"}</button> : null}</div>
      <ul className={css.cards}>{posts.map(p => <CollectedCard key={p.id} p={p} busy={act.busy}
        keep={() => void act.decide(p, "kept")} drop={() => void act.decide(p, "dropped")} />)}</ul>
    </section>
  );
}

export function Collected() {
  const q = useQuery({ queryKey: ["collected", "pending"], queryFn: () => collectedApi.list("pending") });
  const [linkOnly, setLinkOnly] = useState(false);
  const act = useCollected();
  const all = q.data?.posts, posts = all ? (linkOnly ? all.filter(p => !!p.post_url) : all) : undefined;
  return (
    <section className={`paper ${css.box}`} id="collected" aria-labelledby="collected-h">
      <div className={css.head}><h3 id="collected-h">수집 인박스</h3>
        {posts ? <span className={css.headline}>{headline(posts)}</span> : null}
        <label className={css.only}><input type="checkbox" checked={linkOnly} onChange={e => { setLinkOnly(e.target.checked); act.disarm(); }} /> 원문 링크 있는 것만</label></div>
      {act.undo ? <p className={`fok ${css.toast}`} role="status">{act.undo.text}{" "}
        <button type="button" className="tertiary" onClick={act.revert}>되돌리기</button></p>
        : <p className="fok" role="status" aria-atomic="true">{act.note}</p>}
      {act.err ? <p className="ferr" role="alert">{act.err}</p> : null}
      {q.isError && !all ? <LoadFail err={apiErr(q.error)} what="수집 인박스" />
        : !q.data || !posts ? <p className="hint">{LOADING}</p>
        : !q.data.ready ? <p className={`hint ${css.empty}`}>수집 글을 담을 자료 종류(key collected_posts)가 아직 없어요. 만들면 PC가 모은 글이 여기에 쌓여요.</p>
        : !posts.length ? <p className={`hint ${css.empty}`}>{linkOnly && all!.length ? "원문 링크가 있는 새 수집 글이 없어요." : "새로 들어온 수집 글이 없어요. PC가 모은 글이 여기에 쌓여요."}</p>
        : groups(posts).map(g => <Group key={g.grade || "none"} grade={g.grade} label={g.label} posts={g.posts} act={act} />)}
      {q.data?.ready ? <Kept n={q.data.counts.kept} act={act} /> : null}
    </section>
  );
}
