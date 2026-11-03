// 질문·기록 탭 화면(옛 renderQuestionTab·renderRecordTab) — #q·#journal·사용자 탭(#t-…). 껍데기 라우터가 탭을 고르고
// ctx.args = [탭 id, 보기(question|record), 조각(blocks, 띄어쓰기), 고른 질문·글 id] 로 넘긴다. 이 화면은 보기만(결정은 판단 검토).
import type { ScreenProps } from "../../shared/ctx";
import { useRecDialog } from "../../shared/RecDialog";
import { QuestionTab } from "./QuestionTab";
import { RecordTab } from "./RecordTab";

export function SheetScreen({ ctx }: ScreenProps) {
  const S = ctx.state!, [tabId = "q", view = "question", blocks = "", sel = ""] = ctx.args || [];
  const bl = new Set(blocks.split(" ").filter(Boolean));
  const rec = useRecDialog(S);
  return (
    <>
      {view === "record" ? <RecordTab S={S} tabId={tabId} bl={bl} sel={sel} /> : <QuestionTab S={S} tabId={tabId} bl={bl} sel={sel} open={rec.open} />}
      {rec.dialog}
    </>
  );
}
