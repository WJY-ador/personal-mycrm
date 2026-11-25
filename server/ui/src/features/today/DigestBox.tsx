// 수집 인박스 맨 위 「인박스 요약」(2026-11-22 구현계획 4-1). 위 = PC 가 만든 AI 요약(주제 줄: 굵은 이름 + 한 문장 + 글 수) — AI 값, 근거 아님.
// 아래 = 축별 묶음 한 줄(축 코드 + 대기 + 신호, 모델 없이 늘 보인다). 주제 줄·축 칩을 누르면 아래 카드가 그 글만, 다시 누르면 풀린다(따로 버튼 없음).
// 요약이 없거나 요약 뒤 새 대기 글이 있으면 머리에 한 줄(요약은 다음 동기화에서 갱신). 못 불러오면 한 줄만 — 인박스는 그대로 보인다.
import { mdhm } from "../../shared/date";
import { AI_MARK } from "./collectedRows";
import type { Digest, Post } from "./collectedApi";
import css from "./Digest.module.css";

export type Pick = { kind: "theme"; i: number } | { kind: "axis"; id: string } | null;
// 고른 것 → 그 글만(주제 = 요약의 글 id 중 지금 대기, 축 = 그 축이 붙은 글)
export function pickPosts(posts: Post[], d: Digest | undefined, pick: Pick): Post[] {
  if (!pick) return posts;
  if (pick.kind === "axis") return posts.filter(p => p.axes.some(a => a.id === pick.id));
  const ids = new Set(d?.digest?.themes[pick.i]?.item_ids || []);
  return posts.filter(p => ids.has(p.id));
}
const same = (a: Pick, b: Pick) => !!a && !!b && a.kind === b.kind && (a.kind === "theme" ? a.i === (b as { i: number }).i : a.id === (b as { id: string }).id);

type Props = { d: Digest | undefined; fail: boolean; posts: Post[] | undefined; pick: Pick; setPick: (p: Pick) => void };

export function DigestBox({ d, fail, posts, pick, setPick }: Props) {
  if (fail && !d) return <p className={`hint ${css.fail}`} role="status">인박스 요약을 불러오지 못했어요. 아래 목록은 그대로예요.</p>;
  if (!d) return null;
  const g = d.digest, all = posts || [];
  const toggle = (p: Pick) => setPick(same(pick, p) ? null : p);
  const ax = d.by_axis.filter(a => a.pending > 0);
  if (!g && !ax.length && !d.pending_n) return null;
  return (
    <div className={css.box} role="region" aria-labelledby="digest-h" id="digest">
      <div className={css.head}><h4 id="digest-h">인박스 요약</h4>
        {g ? <><span className="chip o-ai">{AI_MARK}</span><span className={css.when}>{`${mdhm(g.made_at)} 기준 대기 ${g.input_n}건 요약`}</span></> : null}</div>
      {!g ? <p className={css.newer} id="digest-none">아직 요약이 없어요. PC 앱에서 인박스 요약을 켜 두면 다음 동기화에서 만들어요.</p>
        : d.new_since > 0 ? <p className={css.newer} id="digest-new">{`요약 뒤 새로 ${d.new_since}건. 요약은 다음 동기화에서 갱신해요.`}</p> : null}
      {g ? <ul className={css.themes}>{g.themes.map((t, i) => {
        const n = pickPosts(all, d, { kind: "theme", i }).length, on = same(pick, { kind: "theme", i });
        return <li key={i}><button type="button" className={css.theme} aria-pressed={on} onClick={() => toggle({ kind: "theme", i })}>
          <b>{t.name}</b><span className={css.line}>{t.line}</span><span className={`chip ${css.n}`}>{n}</span></button></li>;
      })}</ul> : null}
      {ax.length ? <div className={css.axes} role="group" aria-label="축별 대기">{ax.map(a => {
        const on = same(pick, { kind: "axis", id: a.item_id });
        return <button key={a.item_id} type="button" className={`chip ${css.ax}`} aria-pressed={on} title={a.title || ""}
          onClick={() => toggle({ kind: "axis", id: a.item_id })}><b>{a.code || a.title}</b><span>{`대기 ${a.pending}`}</span>
          {a.signal ? <span className={css.sig}>{`신호 ${a.signal}`}</span> : null}</button>;
      })}</div> : null}
    </div>
  );
}
