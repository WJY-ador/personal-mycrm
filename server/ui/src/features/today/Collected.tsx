// 「오늘」 맨 위 수집 인박스(대시보드.app 오늘 탭과 같은 묶음) — 머리(수집 N건, 신호 M, 등급 없음 K) · 「원문 링크 있는 것만」 ·
// 등급 묶음(신호, 소식, 노이즈, 등급 없음) · 소식, 노이즈 머리 「전부 버림」(두 번 눌러 확정) · 판별 뒤 되돌리기 5초 · 아래 접힌 「보관함 N건」.
// 판별 정본은 서버(state pending → kept|dropped). 수집 글은 남의 글이고 판단 근거가 아니다 — 명조를 쓰지 않는다.
// 2026-11-23 두 칸: 넓은 화면(900 초과) = 왼쪽 #collected(요약 상자, 묶음의 촘촘한 줄, 보관함) | 오른쪽 읽기 판(Reader).
// 한 칸(900 이하) = 읽기 판 없이 줄 아래 펼침. 문턱은 useOneCol 과 CSS 가 같은 값. 고른 글은 화면 상태로만(주소에 남기지 않는다).
// 두 칸에서는 왼쪽 상자(data-scroll)가 읽기 판과 같은 높이로 자기 안에서 스크롤한다(수백 건이어도 아래 목록이 밀려나지 않게). 결과 줄(되돌리기)은 상자 위에 붙는다.
import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { apiErr } from "../../shared/api";
import { LoadFail } from "../../shared/LoadFail";
import { axisMap, useAxes } from "../../shared/axes";
import { BULK_GRADES, groups, headline } from "./collectedRows";
import { collectedApi, type Post } from "./collectedApi";
import { CollectedRow, type RowCtx } from "./CollectedRow";
import { DigestBox, pickPosts, type Pick } from "./DigestBox";
import { follow, type At } from "./follow";
import { Reader } from "./Reader";
import { LOADING } from "./text";
import { useCollected } from "./useCollected";
import { useOneCol } from "./useOneCol";
import css from "./Collected.module.css";

const keptQ = { queryKey: ["collected", "kept"], queryFn: () => collectedApi.list("kept") };

function Kept({ n, c }: { n: number; c: RowCtx }) {
  const [open, setOpen] = useState(false);
  const q = useQuery({ ...keptQ, enabled: open });
  const posts = q.data?.posts;
  return (
    <details className={css.kept} open={open} onToggle={e => setOpen((e.currentTarget as HTMLDetailsElement).open)}>
      <summary>{`보관함 ${q.data ? q.data.counts.kept : n}건`}</summary>
      {!open ? null : q.isError && !posts ? <LoadFail err={apiErr(q.error)} what="보관함" /> : !posts ? <p className="hint">{LOADING}</p>
        : !posts.length ? <p className="hint">보관한 수집 글이 없어요.</p>
        : <ul className={css.rows}>{posts.map(p => <CollectedRow key={p.id} p={p} c={c} />)}</ul>}
    </details>
  );
}

function Group({ grade, label, posts, act, c }: { grade: string; label: string; posts: Post[]; act: ReturnType<typeof useCollected>; c: RowCtx }) {
  const armed = act.armed === grade;
  return (
    <section className={css.group} aria-label={label}>
      <div className={css.ghead}><h4>{label}</h4><span className="count">{posts.length}</span>
        {BULK_GRADES.has(grade) ? <button type="button" className={armed ? "secondary small" : "tertiary"} disabled={act.busy}
          onClick={() => act.dropAll(grade, posts)}>{armed ? `한 번 더 누르면 ${posts.length}건 버려요` : "전부 버림"}</button> : null}</div>
      <ul className={css.rows}>{posts.map(p => <CollectedRow key={p.id} p={p} c={c} />)}</ul>
    </section>
  );
}

export function Collected() {
  const q = useQuery({ queryKey: ["collected", "pending"], queryFn: () => collectedApi.list("pending") });
  const dq = useQuery({ queryKey: ["collected", "digest"], queryFn: collectedApi.digest });   // 판별 뒤 refresh() 가 같이 다시 받는다
  const kq = useQuery({ ...keptQ, enabled: false });   // 읽기 판이 보관함 글도 찾게(받기는 열린 보관함이 한다)
  const [linkOnly, setLinkOnly] = useState(false), [pick, setPickRaw] = useState<Pick>(null), [sel, setSel] = useState<string | null>(null);
  const at = useRef<At | null>(null);
  const act = useCollected(), wide = !useOneCol();
  const by = axisMap(useAxes().data?.axes);
  const setPick = (p: Pick) => { setPickRaw(p); act.disarm(); };   // 고른 글이 바뀌면 「전부 버림」 확정 대기를 푼다
  const all = q.data?.posts, shown = all && linkOnly ? all.filter(p => !!p.post_url) : all, posts = shown ? pickPosts(shown, dq.data, pick) : undefined;
  const gs = posts ? groups(posts) : [], kept = kq.data?.posts || [];
  const two = wide && !!q.data?.ready;
  const cur = follow(sel, at.current, [...(all || []), ...kept], [...gs.map(g => ({ key: g.grade || "none", posts: g.posts })), { key: "kept", posts: kept }]);
  const curId = cur.p ? cur.p.id : null;
  useEffect(() => { at.current = cur.at; if (curId !== sel) setSel(curId); });   // 빠진 글 → 다음 글(또는 빈 상태)로 고른 글을 옮긴다
  const c: RowCtx = { by, busy: act.busy, wide: two, sel: curId, choose: setSel, decide: act.decide };
  const box = (
    <section className={`paper ${css.box}`} id="collected" aria-labelledby="collected-h" data-scroll={two ? "" : undefined}>
      <div className={css.head}><h3 id="collected-h">수집 인박스</h3>
        {shown ? <span className={css.headline}>{headline(shown)}</span> : null}
        <label className={css.only}><input type="checkbox" checked={linkOnly} onChange={e => { setLinkOnly(e.target.checked); act.disarm(); }} /> 원문 링크 있는 것만</label></div>
      {q.data?.ready ? <DigestBox d={dq.data} fail={dq.isError} posts={shown} pick={pick} setPick={setPick} /> : null}
      <div className={css.bar}>{act.undo ? <p className={`fok ${css.toast}`} role="status">{act.undo.text}{" "}
        <button type="button" className="tertiary" onClick={act.revert}>되돌리기</button></p>
        : <p className="fok" role="status" aria-atomic="true">{act.note}</p>}
        {act.err ? <p className="ferr" role="alert">{act.err}</p> : null}</div>
      {q.isError && !all ? <LoadFail err={apiErr(q.error)} what="수집 인박스" />
        : !q.data || !posts ? <p className="hint">{LOADING}</p>
        : !q.data.ready ? <p className={`hint ${css.empty}`}>수집 글을 담을 자료 종류(key collected_posts)가 아직 없어요. 만들면 PC가 모은 글이 여기에 쌓여요.</p>
        : !posts.length ? <p className={`hint ${css.empty}`}>{pick && all!.length ? "고른 주제나 축에 남은 대기 글이 없어요." : linkOnly && all!.length ? "원문 링크가 있는 새 수집 글이 없어요." : "새로 들어온 수집 글이 없어요. PC가 모은 글이 여기에 쌓여요."}</p>
        : gs.map(g => <Group key={g.grade || "none"} grade={g.grade} label={g.label} posts={g.posts} act={act} c={c} />)}
      {q.data?.ready ? <Kept n={q.data.counts.kept} c={c} /> : null}
    </section>
  );
  return <div className={two ? css.split : css.solo}>{box}{two ? <Reader p={cur.p} by={by} busy={act.busy} decide={act.decide} /> : null}</div>;
}
