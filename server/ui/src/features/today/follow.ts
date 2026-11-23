// 읽기 판이 따라갈 글 고르기 — 고른 글이 아직 있으면 그대로(거르기로 목록에서 숨어도 유지), 판별 등으로 빠졌으면
// 마지막 자리(같은 묶음, 같은 순번 = 바로 다음 글), 그 자리에도 없거나 빠질 때 보이는 목록에 없었으면 빈 상태. 목록을 다시 받아도 id 로 찾으니 고른 글이 남는다.
import type { Post } from "./collectedApi";

export const READER_ID = "collected-reader";
export type At = { g: string; i: number };            // g = 묶음 열쇠(등급, 등급 없음 = "none", 보관함 = "kept"), i = 묶음 안 순번
export type Lane = { key: string; posts: Post[] };

export function follow(sel: string | null, at: At | null, pool: Post[], lanes: Lane[]): { p: Post | null; at: At | null } {
  if (!sel) return { p: null, at: null };
  const p = pool.find(x => x.id === sel);
  if (p) {
    for (const l of lanes) { const i = l.posts.findIndex(x => x.id === sel); if (i >= 0) return { p, at: { g: l.key, i } }; }
    return { p, at: null };   // 거르기로 숨은 글 — 보이는 자리가 없으니 판별로 빠지면 다음 글을 고르지 않고 빈 상태
  }
  const nx = at ? lanes.find(l => l.key === at.g)?.posts[at.i] || null : null;
  return { p: nx, at: nx ? at : null };
}
