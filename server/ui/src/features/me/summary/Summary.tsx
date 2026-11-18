// 요약 — 블록 순서·props = 레이아웃 저장값의 regions.summary(서버 v2). 모르는 블록 id 는 건너뛴다(레지스트리 밖). 버튼 0(이동 링크만)
// 맨 위 추천 한 줄(2026-11-18 구조추천)은 레이아웃 블록이 아니다 — 서버 /api/structure/hint 가 show 일 때만
import { useQuery } from "@tanstack/react-query";
import { meApi, type Slot } from "../meApi";
import type { World } from "../model";
import type { Blocks } from "./block";
import { readOk } from "../../../shared/state";
import css from "./Summary.module.css";

const RECO_HINT = "추천할 구조가 있어요";   // 구조 추천(2026-11-18) — 담을 규칙 있는 초안이 있거나 안 붙은 기록이 많을 때. 링크 = 내 구조 설정 맨 위 추천 칸

export function Summary({ W, slots, blocks, statsFail }: { W: World; slots: Slot[]; blocks: Blocks; statsFail: boolean }) {
  const firstRecord = readOk(W.S, "journal") && Array.isArray(W.S.journal) && W.S.journal.length === 0
    && W.S.journal_next_before === null && W.recs.length === 0;
  const hint = useQuery({ queryKey: ["me", "structure-hint", W.S.generated || ""], queryFn: meApi.hint, staleTime: 60_000 });   // 실패 = 줄 없음
  return (
    <>
      {hint.data?.show && <p className="hint" id="reco-hint"><a href="#_setup/structure">{RECO_HINT}</a></p>}
      {firstRecord && <section className={css.firstRecord} id="first-record-intro" aria-labelledby="first-record-title">
        <h2 id="first-record-title">첫 기록을 남겨 보세요</h2>
        <p>ChatGPT나 Claude에 MyCRM을 연결한 대화에서 기록을 남기고, 검토할 판단 후보를 여기서 확인할 수 있어요.</p>
        <ol aria-label="첫 기록을 남기는 순서">
          <li>AI 대화 연결</li><li>기록 남기기</li><li>후보 검토</li>
        </ol>
        <p className={css.webChatNote}>웹의 AI는 본인 PC 연결과 로컬 에이전트 실행이 필요해요.</p>
        <a className={css.helpLink} href="/help">첫 기록 안내 보기</a>
      </section>}
      <div className={css.sum} id="me-summary">
        {slots.filter(s => blocks[s.c]).map((s, i) => { const B = blocks[s.c]; return <B key={`${s.c}${i}`} p={s.p || {}} W={W} statsFail={statsFail} />; })}
      </div>
    </>
  );
}
