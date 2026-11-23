// 요약 — 블록 순서·props = 레이아웃 저장값의 regions.summary(서버 v2). 모르는 블록 id 는 건너뛴다(레지스트리 밖). 블록은 버튼 0(이동 링크만), 첫 기록 카드만 입력칸과 [남기기]
// 맨 위 추천 한 줄(2026-11-18 구조추천)은 레이아웃 블록이 아니다 — 서버 /api/structure/hint 가 show 일 때만
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { meApi, type Slot } from "../meApi";
import type { World } from "../model";
import type { Blocks } from "./block";
import { readOk } from "../../../shared/state";
import { FirstRecord } from "./FirstRecord";
import css from "./Summary.module.css";

const RECO_HINT = "추천할 구조가 있어요";   // 구조 추천(2026-11-18) — 담을 규칙 있는 초안이 있거나 안 붙은 기록이 많을 때. 링크 = 내 구조 설정 맨 위 추천 칸

export function Summary({ W, slots, blocks, statsFail }: { W: World; slots: Slot[]; blocks: Blocks; statsFail: boolean }) {
  const firstRecord = readOk(W.S, "journal") && Array.isArray(W.S.journal) && W.S.journal.length === 0
    && W.S.journal_next_before === null && W.recs.length === 0;
  const [saved, setSaved] = useState(false);   // 방금 여기서 첫 글을 저장함 — 이 화면에 머무는 동안만 카드를 저장됨 모양으로 남긴다(컴포넌트 상태)
  const hint = useQuery({ queryKey: ["me", "structure-hint", W.S.generated || ""], queryFn: meApi.hint, staleTime: 60_000 });   // 실패 = 줄 없음
  return (
    <>
      {hint.data?.show && <p className="hint" id="reco-hint"><a href="#_setup/structure">{RECO_HINT}</a></p>}
      {(firstRecord || saved) && <FirstRecord saved={saved} onSaved={() => setSaved(true)} />}
      <div className={css.sum} id="me-summary">
        {slots.filter(s => blocks[s.c]).map((s, i) => { const B = blocks[s.c]; return <B key={`${s.c}${i}`} p={s.p || {}} W={W} statsFail={statsFail} />; })}
      </div>
    </>
  );
}
