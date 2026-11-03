// 확정 전 재검토 — 후보의 review = 근거 기록의 사유 코드(서버 CANDIDATE-REVIEW 와 같은 뜻). 정정 안내는 author_unknown·processed 에만
const TEXT: Record<string, string> = {
  author_unknown: "근거 글의 작성자를 확인할 수 없어 이 판단을 확정할 수 없어요.",
  external: "근거 글이 남이 쓴 글이라 이 판단을 확정할 수 없어요.",
  processed: "근거 글이 원문 그대로가 아니라 이 판단을 확정할 수 없어요.",
  deleted: "근거 글이 삭제돼 이 판단을 확정할 수 없어요.",
};
const FIX: Record<string, string> = {
  author_unknown: "작성자 정보가 실제로 틀렸을 때만 연결한 AI 대화에서 글 정보를 정정하세요.",
  processed: "가공 방식 정보가 실제로 틀렸을 때만 연결한 AI 대화에서 글 정보를 정정하세요.",
};

export function ReviewNote({ review }: { review: string | null }) {
  if (!review) return null;
  return (
    <p className="recheck"><span className="chip flag">확정 전 재검토</span>
      {TEXT[review] || "근거 글이 인용 조건에 맞지 않아 이 판단을 확정할 수 없어요."}
      {` ${FIX[review] ? FIX[review] + " " : ""}반영 안 함이나 아직 안 정함으로 둘 수는 있어요.`}</p>
  );
}
