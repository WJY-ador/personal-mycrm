// 상세의 동작 칸 — 동시에 최대 3개 + [삭제](휴지통 켜짐일 때만), 편집 중엔 숨긴다. 버튼 한 번 = 쓰기 한 번(옛 homeActs·homeDo 그대로).
// [고쳐서 남기기] = 판단 문장 인라인 편집(기존 edit_confirm). 결과 문구는 그 자리에 짧게.
import { useEdit } from "../../shared/edit";
import { meApi } from "./meApi";
import type { Row, World } from "./model";
import { tabOfItem } from "./model";
import { trashErr } from "../../shared/item";
import { oldErrText, TRASH_ASK, TRASH_DONE } from "./text";

const ITEM_DONE: Record<string, string> = { confirm: "남겼어요.", exclude: "반영 안 함으로 표시했어요.", pending: "되돌렸어요.", apply: "제안을 적용했어요.", discard: "제안을 제외했어요." };

export function Acts({ W, r, trashOn }: { W: World; r: Row; trashOn: boolean }) {
  const { edit, act, run, start } = useEdit();
  if (edit) return null;
  const busy = !!act?.busy;
  const btn = (cls: string, label: string, go: () => void) => <button key={label} className={cls} type="button" disabled={busy} onClick={go}>{label}</button>;
  const bs: React.ReactNode[] = [];
  if (r.k === "cand" && r.x.status === "pending") {
    const x = r.x, decide = (action: string, done: string, after = "") =>
      run(() => meApi.candidate({ candidate_id: x.id, action, expected_revision: x.revision }), done, oldErrText, after);
    const ex = () => decide("exclude", "반영 안 함으로 표시했어요. 목록에서 빠졌어요.", "#_me");
    if (x.review) bs.push(btn("secondary", "반영 안 함", ex));
    else bs.push(btn("primary", "남기기", () => decide("confirm", "확정한 판단으로 남겼어요.")),
      btn("secondary", "고쳐서 남기기", () => start({ key: "cand:" + x.id, done: "고친 문장을 확정한 판단으로 남겼어요.", errText: oldErrText,
        fields: [{ name: "text", label: "고친 문장", multi: true, orig: x.text }],
        save: d => meApi.candidate({ candidate_id: x.id, action: "edit_confirm", text: d.text, expected_revision: x.revision }) })),
      btn("tertiary", "반영 안 함", ex));
  } else if (r.k === "refl") {
    const x = r.x, to = x.review !== "reviewed";
    bs.push(btn(to ? "primary" : "secondary", to ? "확인했어요" : "확인 전으로",
      () => run(() => meApi.review(x.id, to, x.revision), to ? "확인했어요로 바꿨어요." : "확인 전으로 바꿨어요.", oldErrText)));
  } else if (r.k === "item" && r.x.revision) {
    const x = r.x, decide = (action: string) => run(() => meApi.itemDecide({ item_id: x.id, expected_revision: x.revision, action,
      ...(action === "apply" || action === "discard" ? { proposal_id: x.proposal!.proposal_id } : {}) }), ITEM_DONE[action] || "저장했어요.", oldErrText);
    if (x.proposal) bs.push(btn("primary", "제안 적용", () => decide("apply")), btn("secondary", "제안 제외", () => decide("discard")));
    else if (x.semantic_kind === "principle" && trashOn) { if (x.decision !== "confirmed") bs.push(btn("primary", "남기기", () => decide("confirm"))); }
    else if (x.semantic_kind === "principle")
      for (const [a, c, l, st] of [["confirm", "primary", "남기기", "confirmed"], ["exclude", "secondary", "반영 안 함", "excluded"], ["pending", "tertiary", "되돌리기", "pending"]])
        if (st !== (x.decision || "pending")) bs.push(btn(c, l, () => decide(a)));
  }
  // [삭제] — 휴지통 켜짐일 때만. 후보는 독립 휴지통 대상이 아니라 없다
  const del = (kind: string, id: string, rev: number | null, back: string) =>
    bs.push(btn("secondary", "삭제", () => { if (window.confirm(TRASH_ASK)) void run(() => meApi.trash(kind, id, rev), TRASH_DONE, trashErr, back); }));
  if (trashOn && r.k === "journal") del("record", r.id, null, "#_me");
  else if (trashOn && r.k === "item" && r.x.revision) del("item", r.id, r.x.revision, "#_me/" + tabOfItem(W, r.x));
  else if (trashOn && r.k === "refl") del("reflection", r.id, r.x.revision, "#_me");
  return (
    <>
      {bs.length > 0 && <div className="hacts" role="group" aria-label="동작">{bs}</div>}
      <p className="ferr" role="alert" aria-atomic="true">{act?.err}</p>
      <p className="fok" role="status" aria-atomic="true">{act?.ok}</p>
    </>
  );
}
