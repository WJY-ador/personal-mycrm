// 읽기 판 긴 요약 요청과 기다림(2026-11-25 구현계획 1절, 4절). 사용자가 고른 글(끌어 놓기, Enter, 터치 누름, 다시 만들기)에
// AI 긴 요약이 없을 때만 POST /api/jobs {kind: "collected_long", text: 항목 id} 를 보내고 GET /api/jobs/<id>?wait=30 으로 기다린다.
// 보내기 전에 그 글이 든 목록을 한 번 다시 받는다 — 다른 글로 간 사이 끝난 작업의 요약이 있으면 보내지 않고 그대로 보인다(같은 글 새 작업, 하루 한도 낭비 방지).
// 끝나면(confirmed) 목록을 다시 받아 읽기 판을 채운다(서버가 항목 ai_* 를 이미 썼다). 다시 받은 글에도 요약이 없으면 실패로 끝낸다(자동 재요청 없음).
// 판별 뒤 자동으로 넘어온 글은 보내지 않는다(auto). 다른 글로 바꾸면 화면의 기다림만 멈춘다(작업은 PC 에서 끝나고 다음에 열면 보인다).
// 웹 롱폴은 사용자당 동시 2, 분당 12 — 두 확인의 시작을 POLL_GAP_MS 이상 띄우고, RATE-LIMIT 은 실패가 아니라 잠시 뒤 다시 확인.
// 확인이 queued 이고 SLOW_MS 넘게 지났으면(작업의 created_at 기준, 같은 항목의 열린 작업을 다시 받은 경우도 맞게) PC 꺼짐 안내.
// 롱폴은 queued 에서 leased 로 넘어가도 돌아오지 않으니 따로 타이머를 두지 않고 확인이 돌아올 때만 판정한다(늦어도 30초).
import { useEffect, useState } from "react";
import { apiErr } from "../../shared/api";
import { queryClient } from "../../shared/queries";
import { collectedApi, type LongJob, type Post, type PostList } from "./collectedApi";
import { hasLong } from "./collectedRows";

export type Ask = { id: string; n: number };   // 사용자가 고른 글 id + 요청 차례(다시 만들기, 다른 글로 갔다 다시 고르기 = 새 요청)
// none = 표시 없음(글 없음, 요약 있음) · auto = 자동으로 넘어온 글 · wait, slow = 기다림 · nodevice, short, fail = 끝(fail 만 다시 만들기)
export type Long = "none" | "auto" | "wait" | "slow" | "nodevice" | "short" | "fail";
export const SLOW_MS = 120_000, POLL_GAP_MS = 5_000;
export const LONG_SHORT = "long-short";   // PC 가 원문 300자 미만으로 부르지 않은 실패(reason_code)
const LIVE = new Set(["queued", "leased", "running"]);
const DONE = new Set(["confirmed", "result_ready"]);   // result_ready 는 이 종류에서 머물지 않는다(서버가 바로 confirmed) — 오면 끝난 것으로
const sleep = (ms: number) => new Promise(r => setTimeout(r, ms));

// 끝난 뒤 그 글이 든 목록을 다시 받는다 — 보관함이 닫혀 있어도(조회가 꺼져 있어도) 보관함 글을 채우게 직접 받는다
// 반환 = 다시 받은 목록의 그 글(없으면 null — 다른 곳에서 판별돼 빠졌다)
async function reload(p: Post): Promise<Post | null> {
  const which = p.state === "kept" ? "kept" : "pending";
  await Promise.all([queryClient.invalidateQueries({ queryKey: ["collected"] }),
    queryClient.fetchQuery({ queryKey: ["collected", which], queryFn: () => collectedApi.list(which), staleTime: 0 })]);
  return queryClient.getQueryData<PostList>(["collected", which])?.posts.find(x => x.id === p.id) || null;
}

export function useLong(p: Post | null, ask: Ask | null): Long {
  const id = p ? p.id : null, need = !!p && !hasLong(p), mine = need && !!ask && ask.id === id;
  const key = mine ? `${id}:${ask!.n}` : "";
  const [st, setSt] = useState<{ key: string; s: Long | "done" }>({ key: "", s: "wait" });
  useEffect(() => {
    if (!mine || !p) return;
    let live = true;
    const put = (s: Long | "done") => { if (live) setSt({ key, s }); };
    put("wait");   // 같은 글로 돌아온 새 요청 — 지난 끝 상태를 지운다
    void (async () => {
      let jid: string;
      try {
        const now = await reload(p);
        if (!live || !now || hasLong(now)) return;   // 요약이 이미 있거나 글이 빠졌다 — 화면은 다시 받은 목록으로 바뀐다
        jid = (await collectedApi.long(p.id)).id;
      }
      catch (x) { put(apiErr(x).code === "NO-DEVICE" ? "nodevice" : "fail"); return; }
      const t0 = Date.now();
      while (live) {
        const t = Date.now();
        let j: LongJob | null = null;
        try { j = await collectedApi.job(jid); }
        catch (x) { if (apiErr(x).code !== "RATE-LIMIT") { put("fail"); return; } }
        if (!live) return;
        if (j && DONE.has(j.status)) { await reload(p).catch(() => undefined); put("done"); return; }
        if (j && !LIVE.has(j.status)) { put(j.status === "failed" && j.reason_code === LONG_SHORT ? "short" : "fail"); return; }
        if (j) put(j.status === "queued" && Date.now() - Math.min(t0, Date.parse(j.created_at) || t0) >= SLOW_MS ? "slow" : "wait");
        await sleep(Math.max(0, POLL_GAP_MS - (Date.now() - t)));
      }
    })();
    return () => { live = false; };
  }, [key]);   // 글 객체가 다시 받아져도 같은 요청(key)이면 다시 보내지 않는다
  if (!p || !need) return "none";
  if (!mine) return "auto";
  const s = st.key === key ? st.s : "wait";
  return s === "done" ? "fail" : s;   // 끝났는데 다시 받은 글에 요약이 없다
}
