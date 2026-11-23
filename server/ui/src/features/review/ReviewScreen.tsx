// 판단 검토(원문과 대조하기) — 라우트 #<탭>/review/<질문ID | r:기록ID>/<후보ID>. 그 범위의 아직 안 정한 판단을 세로로 전부 나열하고, 여기서 결정을 저장한다.
// 껍데기가 넘기는 args = [탭 id, 목록 키, 후보 자리, 돌아갈 주소, 돌아가기 문구](돌아갈 곳은 껍데기 라우터가 기억). 후보 자리가 목록의 후보면
// 들어올 때 그 카드로 스크롤하고 포커스한다. 옛 숫자 idx, end, 빈 자리, 이미 정한 후보는 목록 맨 위로 본다(주소는 고쳐 쓰지 않는다).
// 저장 = 호출 하나(confirm, exclude, edit_confirm) → 상태를 다시 받아 그린다. 정한 카드는 목록에서 빠지고, 결과 한 줄은 다음 카드 위(없으면 머리)에,
// 포커스는 다음 카드(없으면 머리)로 간다. 저장 중엔 모든 카드의 결정을 잠근다(요청과 다시 받기가 끝날 때까지, 새 상태가 와도 풀지 않는다).
// 저장 뒤 다시 받기는 원문(journal)을 뺀다. 결정은 글 본문을 바꾸지 않는다. 충돌, 새로 고침, 표지 갱신은 원문도 다시 받는다.
// 서버 msg 는 그대로 보인다(CONFLICT 는 서버 문구 + 고치던 문장). 응답 유실은 상태 변화만으로 해당 요청의 저장 여부를 증명할 수 없어 불확실로 남긴다.
// 미저장 보호 = 고친 카드의 등록부(후보 id → 고치기 시작한 주소). 하나라도 남으면 그 주소를 ctx.setDirty, 모두 깨끗할 때만 null.
// 고친 문장을 저장한 것은 edit_confirm 성공뿐 — 남기기, 남기지 않기는 등록을 풀지 않는다(다시 받기에 성공하면 카드가 사라지며 풀린다).
import { useCallback, useEffect, useRef, useState } from "react";
import { apiErr } from "../../shared/api";
import type { ScreenProps, UiCtx } from "../../shared/ctx";
import { candidateDecide, JOURNAL } from "../../shared/journal";
import { readOk, type Cand } from "../../shared/state";
import { Card } from "./Card";
import { PartFail } from "../../shared/PartFail";
import { CONFLICT_TEXT, NO_QUESTION, SAVE_FAIL, SAVING, UNKNOWN, unsavedEdit, WORDS as w } from "./text";
import css from "./Review.module.css";

// 등록부 — mark(id, true) = 그 카드 등록(처음 고친 때의 주소), mark(id, false) = 그 카드만 해제. 없는 카드 해제는 아무것도 안 한다
// (다른 카드의 등록을 지우지 않게). 화면이 사라지면 등록부를 비우고 해제한다.
export function useDirtyCards(ctx: UiCtx) {
  const ctxRef = useRef(ctx), at = useRef(new Map<string, string>());
  ctxRef.current = ctx;
  const mark = useCallback((id: string, dirty: boolean) => {
    const m = at.current;
    if (dirty === m.has(id)) return;
    if (dirty) m.set(id, location.hash); else m.delete(id);
    ctxRef.current.setDirty?.(m.size ? m.values().next().value! : null);
  }, []);
  useEffect(() => () => {
    if (!at.current.size) return;
    at.current.clear(); ctxRef.current.setDirty?.(null);
  }, []);
  return mark;
}

// at = 문구를 보일 카드 id(빈 글자 = 머리), lead = 그 카드 위(앞 카드가 빠진 결과), scope = 문구를 낸 범위(범위가 바뀌면 보이지 않는다)
type Say = { text: string; err?: string; at: string; lead?: boolean; scope: string };

// 카드로 가기 — 스크롤은 즉시(부드러운 이동 없음), 포커스는 스크롤 없이. lead = 결정 뒤(결과 한 줄이 보이는 자리로, 이미 다 보이면 스크롤하지 않는다)
// 스크롤 위쪽 여백은 CSS 의 scroll-margin-top(.item, .lead)
const goCard = (id: string, lead = false) => {
  const n = document.getElementById("cand-" + id), t = lead ? document.getElementById("lead-" + id) : n;
  const r = t?.getBoundingClientRect(), seen = !!r && r.top >= 0 && r.bottom <= innerHeight;
  if (t && !(lead && seen)) t.scrollIntoView?.({ block: "start" });
  n?.focus({ preventScroll: true });
};

export function ReviewScreen({ ctx }: ScreenProps) {
  const S = ctx.state!, [, qid = "", key = "", back = "#", backText = ""] = ctx.args || [];
  const [say, setSay] = useState<Say>({ text: "", at: "", scope: "" });
  const [busy, setBusy] = useState(false);   // 저장 중 = 결정 요청이 진행 중(다시 받기까지). 어느 길로 끝나도 finally 에서 푼다
  // 이 화면에 있는 동안만 머리글의 막대, 범례, 질문 줄을 숨긴다(Review.module.css 의 body.review-screen, 디자인 2 C3). 빈, 못 읽음 상태도 같다
  useEffect(() => { document.body.classList.add("review-screen"); return () => document.body.classList.remove("review-screen"); }, []);
  const mark = useDirtyCards(ctx);
  const after = useRef<{ id: string; nextId: string } | null>(null), flash = useRef<string | null>(null), title = useRef<HTMLHeadingElement>(null);
  const go = useRef<string | null>(null);   // 결과 한 줄을 그린 뒤 갈 카드(결정 뒤, 한 번)
  const went = useRef("");   // 들어올 때 카드로 간 주소(같은 주소에선 다시 가지 않는다 — 주기 갱신으로 다시 그려도 포커스를 뺏지 않게)

  const byRec = qid.startsWith("r:");
  const q = byRec ? null : (S.questions || []).find(x => x.id === qid);
  const rec = byRec ? (S.journal || []).find(j => j.id === qid.slice(2)) : null;
  const qText = byRec ? `${NO_QUESTION}, ${w.record}: ${rec ? rec.title : w.recGone}` : q ? q.text : "찾을 수 없는 질문";
  const ok = readOk(S, "candidates");
  const scopeReadOk = readOk(S, byRec ? "journal" : "questions");
  const scopePending = scopeReadOk && byRec && !rec && S.journal_next_before !== null;
  const scopeMissing = scopeReadOk && (byRec ? !rec && S.journal_next_before === null : !q);
  const scopeValid = scopeReadOk && !scopePending && !scopeMissing;
  const pend = (S.candidates || []).filter(c => c.status === "pending");
  const wait = !ok ? [] : byRec ? pend.filter(c => !c.question_id && c.record_id === qid.slice(2)) : pend.filter(c => c.question_id === qid);
  const ids = wait.map(c => c.id).join(" ");
  useEffect(() => {   // 들어올 때 — 주소의 후보가 목록에 있으면 그 카드로, 아니면 목록 맨 위 그대로
    const k = `${qid}/${key}`;
    if (!ok || !scopeValid || went.current === k) return;
    went.current = k;
    if (wait.some(c => c.id === key)) goCard(key);
  }, [ok, scopeValid, qid, key, ids]);
  useEffect(() => {   // 새 상태 = 저장 뒤 다시 받은 상태 — 결과 문구와 포커스는 이번 한 번만
    const a = after.current, msg = flash.current;
    after.current = null; flash.current = null;
    if (!a || msg === null) return;
    const has = (id: string) => wait.some(c => c.id === id);
    if (has(a.id)) setSay({ text: msg, at: a.id, scope: qid });   // 카드가 남았다(충돌 등) — 그 카드에
    else if (a.nextId && has(a.nextId)) { go.current = a.nextId; setSay({ text: msg, at: a.nextId, lead: true, scope: qid }); }
    else { setSay({ text: msg, at: "", scope: qid }); title.current?.focus(); }
  }, [S]);
  useEffect(() => {   // 결과 한 줄이 그려진 뒤에 재야 그 줄의 자리가 맞다
    const id = go.current;
    go.current = null;
    if (id) goCard(id, true);
  }, [say]);
  const shown = say.scope === qid ? say : null;
  const headText = shown && !shown.at ? shown.text : "";
  const head = (m: number, link: boolean) => (
    <div className={css.head}><h2 id="review-title" tabIndex={-1} ref={title}>원문과 대조하기</h2>
      {m > 0 && <p className={css.pos}>아직 안 정한 문장 {m}개</p>}{link && <a className="link" href={back}>{backText}</a>}</div>
  );
  const statusP = <p id="save-status" className={css.status} role="status" aria-atomic="true">{headText}</p>;
  if (!ok) return <>{head(0, true)}<div className="paper"><PartFail err={{ code: "", msg: "", ...S.read!.candidates.error }} what="문장 목록" recMissing={w.recMissing} /></div></>;
  if (!scopeReadOk) return <>{head(0, true)}<div className="paper"><PartFail err={{ code: "", msg: "", ...S.read?.[byRec ? "journal" : "questions"]?.error }} what={byRec ? "내 글 목록" : "질문 목록"} recMissing={w.recMissing} /></div></>;
  if (scopePending) return <>{head(0, true)}<div className={`paper ${css.done}`}><b>기록을 확인할 수 없어요.</b>
    <p>이 기록이 현재 목록에 없어 검토가 끝났는지 확인하지 못했어요.</p>
    <div className={css.row}><a className="btn primary" href={back}>{backText}</a></div></div></>;
  if (scopeMissing) return <>{head(0, true)}<div className={`paper ${css.done}`}><b>{byRec ? "이 기록을 찾을 수 없어요." : "이 질문을 찾을 수 없어요."}</b>
    <div className={css.row}><a className="btn primary" href={back}>{backText}</a></div></div></>;
  if (!wait.length) {
    return <>{head(0, false)}<div className={`paper ${css.done}`}><b>아직 안 정한 문장이 없어요.</b>
      <p className={css.scopeDone}>{byRec ? "이 기록의 미결 문장 검토가 끝났어요." : "이 질문의 미결 문장 검토가 끝났어요."}</p><p>{w.emptyHint}</p>
      <div className={css.row}><a className="btn primary" href={back}>{backText}</a><a className="link" href="#structure/cand/confirmed">전체 확정 판단 보기</a></div>{statusP}</div></>;
  }

  // saved = 카드에 저장 성공 알림(기준 바꾸기) · baseRev = 카드 기준 문장의 revision(고친 문장 저장만 이것으로 충돌 검사, 남기기, 남기지 않기는 보이는 최신 revision)
  async function decide(c: Cand, action: string, text: string | undefined, saved: () => void, baseRev: number) {
    if (busy) return;
    const rev = action === "edit_confirm" ? baseRev : c.revision;
    const i = wait.findIndex(x => x.id === c.id), nextId = wait[i + 1]?.id || "";
    const here = (t: Partial<Say>) => setSay({ text: "", at: c.id, scope: qid, ...t });
    const ack = () => { if (action === "edit_confirm") { saved(); mark(c.id, false); } };   // 고친 문장 저장만 — 다시 받기 전에 푼다
    const done = async (msg: string, keep?: string) => {   // 저장됨(또는 충돌) — 상태를 다시 받아 그린다. 못 받으면 문구만 그 카드에
      after.current = { id: c.id, nextId }; flash.current = msg;
      if (!(await ctx.reload(keep))) { after.current = null; flash.current = null; here({ text: msg }); }
    };
    here({ text: SAVING }); setBusy(true);
    const body = { candidate_id: c.id, action, ...(Number.isInteger(rev) ? { expected_revision: rev } : {}), ...(action === "edit_confirm" ? { text } : {}) };
    try {
      try {
        await candidateDecide(body, typeof AbortSignal.timeout === "function" ? AbortSignal.timeout(15000) : undefined);
      } catch (e) {
        const er = apiErr(e);
        if (er.code === "UNAUTHORIZED") return;
        if (er.code === "OFFLINE") {
          // 응답 유실 뒤 상태 변화만으로 이 요청의 저장 여부를 증명할 수 없다. 다른 기기의 같은 결정일 수도 있다.
          here({ err: UNKNOWN });
          return;
        }
        if (er.code === "CONFLICT") return await done((er.msg || CONFLICT_TEXT) + (action === "edit_confirm" && text !== c.text ? unsavedEdit(text || "") : ""));
        here({ err: er.msg || SAVE_FAIL });
        return;
      }
      ack();   // 저장됨 — edit_confirm 이면 카드 기준을 바꾸고 등록을 푼다
      await done(w.saved(action), JOURNAL);   // 저장됨 = 본문은 그대로, 원문은 다시 받지 않는다
    } finally { setBusy(false); }
  }
  // 결정 영역 설명은 목록 머리에 한 문장(디자인 2 C3) — 남기면 어디로 가는지 + 남기지 않음이 지우지 않는다는 것
  const dest = byRec ? `남기면 ${w.mine}에 들어가고(${NO_QUESTION}), ${w.keepNote}` : `남기면 이 질문의 ${w.mine}에 들어가고, ${w.keepNote}`;
  const locked = busy;
  const of = (c: Cand, lead: boolean) => (shown && shown.at === c.id && !!shown.lead === lead ? shown : null);
  return (
    <div className={css.review}>{head(wait.length, true)}
      <div className={css.scope}><p className={css.q}>{byRec ? "" : "질문: "}{qText}</p><p id="decision-help" className={css.dest}>{dest}</p>{statusP}</div>
      <div>{wait.map((c, n) => (
        <Card key={c.id} S={S} c={c} n={n + 1} w={w} locked={locked} lead={of(c, true)?.text || ""} status={of(c, false)?.text || ""} err={of(c, false)?.err || ""}
          onDecide={(a, t, s, r) => void decide(c, a, t, s, r)} onDirty={d => mark(c.id, d)} />))}</div>
    </div>
  );
}
