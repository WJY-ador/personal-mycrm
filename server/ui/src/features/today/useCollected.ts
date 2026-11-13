// 수집 인박스 동작 — 판별 하나(성공하면 목록에서 뺀다 + 되돌리기 5초) · 되돌리기(직전 상태로 판별) · 묶음 버림(두 번 눌러 확정, 200건씩).
// 판별 뒤 인박스·보관함 조회를 다시 받는다. 충돌(다른 곳에서 먼저 바뀜)은 다시 받고 한 줄 안내.
import { useEffect, useState } from "react";
import { apiErr } from "../../shared/api";
import { postMsg } from "../../shared/postErr";
import { queryClient } from "../../shared/queries";
import { UNDO_MS } from "./collectedRows";
import { BULK_MAX, collectedApi, type Post, type PostList } from "./collectedApi";

export type Undo = { id: string; text: string; back: string; revision: number };
const WORD: Record<string, string> = { kept: "보관했어요.", dropped: "버렸어요." };

function forget(ids: string[]) {   // 판별한 글을 두 목록에서 바로 뺀다(다시 받기 전 깜빡임 없이)
  for (const k of ["pending", "kept"]) queryClient.setQueryData<PostList>(["collected", k], d => d && { ...d, posts: d.posts.filter(p => !ids.includes(p.id)) });
}
const refresh = () => queryClient.invalidateQueries({ queryKey: ["collected"] });

export function useCollected() {
  const [busy, setBusy] = useState(false), [err, setErr] = useState(""), [note, setNote] = useState("");
  const [undo, setUndo] = useState<Undo | null>(null), [armed, setArmed] = useState("");
  useEffect(() => {
    if (!undo) return;
    const t = setTimeout(() => setUndo(null), UNDO_MS);
    return () => clearTimeout(t);
  }, [undo]);

  async function run(call: () => Promise<void>) {
    setErr(""); setNote(""); setBusy(true);
    try { await call(); } catch (x) { setErr(postMsg(apiErr(x))); }
    setBusy(false);
    await refresh();
  }
  const decide = (p: Post, state: string) => run(async () => {
    const r = await collectedApi.decide(p.id, state, p.revision);
    forget([p.id]);
    setUndo({ id: p.id, text: WORD[state] || "", back: p.state, revision: r.revision });
  });
  const revert = () => {
    const u = undo;
    if (!u) return;
    setUndo(null);
    void run(async () => { await collectedApi.decide(u.id, u.back, u.revision); setNote("되돌렸어요."); });
  };
  const dropAll = (grade: string, posts: Post[]) => {
    if (armed !== grade) { setArmed(grade); return; }
    setArmed(""); setUndo(null);
    void run(async () => {
      const ids = posts.map(p => p.id);
      let n = 0;
      for (let i = 0; i < ids.length; i += BULK_MAX) n += (await collectedApi.drop(ids.slice(i, i + BULK_MAX))).dropped.length;
      forget(ids);
      setNote(`${n}건 버렸어요.`);
    });
  };
  return { busy, err, note, undo, armed, decide, revert, dropAll, disarm: () => setArmed("") };
}
