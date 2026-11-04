// 판단 검토(원문과 대조하기) — 라우트 #<탭>/review/<질문ID | r:기록ID>/<후보ID | end>. 아직 안 정한 판단을 한 장씩, 여기서 결정을 저장한다.
// 껍데기가 넘기는 args = [탭 id, 목록 키, 후보 자리, 돌아갈 주소, 돌아가기 문구](돌아갈 곳은 껍데기 라우터가 기억). 옛 숫자 idx·이미 정한 후보는
// 그 자리의 후보로 주소를 바꿔 끼운다(replace). 저장 = 호출 하나(confirm · exclude · edit_confirm) → 상태를 다시 받아 다음 판단으로.
// 서버 msg 는 그대로 보인다(CONFLICT 는 서버 문구 + 고치던 문장). 응답을 못 받으면 상태를 다시 읽어 그 판단이 바뀌었는지 본다.
import { useEffect, useRef, useState } from "react";
import { apiErr, getJSON } from "../../shared/api";
import type { ScreenProps } from "../../shared/ctx";
import { candidateDecide } from "../../shared/journal";
import { readOk, type AppState, type Cand } from "../../shared/state";
import { Card } from "./Card";
import { PartFail } from "../../shared/PartFail";
import { CHECKING, CONFLICT_TEXT, NO_QUESTION, SAVE_FAIL, SAVING, UNKNOWN, unsavedEdit, WORDS as w } from "./text";
import css from "./Review.module.css";

type Say = { text: string; err?: string; pin: string | null; focus?: boolean };   // pin = 이 문구를 보일 화면(null = 다음에 그리는 화면에 한 번)

export function ReviewScreen({ ctx }: ScreenProps) {
  const S = ctx.state!, [tabId = "", qid = "", key = "", back = "#", backText = ""] = ctx.args || [];
  const [say, setSay] = useState<Say>({ text: "", pin: null });
  const [lockS, setLockS] = useState<AppState | null>(null);   // 저장 중 = 잠근 때의 상태 — 새 상태가 오면 저절로 풀린다
  const after = useRef<{ qid: string; nextId: string } | null>(null), flash = useRef<string | null>(null), title = useRef<HTMLHeadingElement>(null);

  const byRec = qid.startsWith("r:");
  const q = byRec ? null : (S.questions || []).find(x => x.id === qid);
  const rec = byRec ? (S.journal || []).find(j => j.id === qid.slice(2)) : null;
  const qText = byRec ? `${NO_QUESTION} · ${w.record} 「${rec ? rec.title : w.recGone}」` : q ? q.text : "찾을 수 없는 질문";
  const base = `#${tabId}/review/${qid}/`;
  const ok = readOk(S, "candidates");
  const scopeReadOk = readOk(S, byRec ? "journal" : "questions");
  const scopePending = scopeReadOk && byRec && !rec && S.journal_next_before !== null;
  const scopeMissing = scopeReadOk && (byRec ? !rec && S.journal_next_before === null : !q);
  const scopeValid = scopeReadOk && !scopePending && !scopeMissing;
  const pend = (S.candidates || []).filter(c => c.status === "pending");
  const wait = !ok ? [] : byRec ? pend.filter(c => !c.question_id && c.record_id === qid.slice(2)) : pend.filter(c => c.question_id === qid);
  const idx = wait.findIndex(x => x.id === key);
  let target = "";
  if (ok && scopeValid && !key.startsWith("c_") && key !== "end") {   // 옛 숫자 idx(또는 빈 자리)
    const t = wait[parseInt(key || "0", 10) || 0];
    target = t ? t.id : wait.length ? "end" : "";
  }
  if (ok && scopeValid && key.startsWith("c_") && idx < 0) {   // 이미 정한(또는 없는) 판단 — 저장 직후면 기억해 둔 다음, 아니면 남은 첫 판단
    const nav = after.current?.qid === qid ? after.current : null;
    target = ((nav && wait.find(x => x.id === nav.nextId)) || wait[0])?.id || "";
  }
  const drawn = target ? "" : `${qid}/${key}`;
  useEffect(() => { if (target) location.replace(base + target); }, [base, target]);
  useEffect(() => {   // 새 상태 = 저장 뒤 다시 받은 상태 — 기억해 둔 다음 판단은 이번 한 번만, 결과 문구는 다음에 그리는 화면에
    after.current = null;
    if (flash.current !== null) { setSay({ text: flash.current, pin: null, focus: true }); flash.current = null; }
  }, [S]);
  useEffect(() => {
    if (!drawn || say.pin !== null || !say.text) return;
    setSay({ text: say.text, pin: drawn });
    if (say.focus) title.current?.focus();
  }, [drawn, say]);
  const status = say.pin === drawn ? say.text : "", err = say.pin === drawn ? say.err || "" : "";
  const head = (m: number, link: boolean) => (
    <div className={css.head}><h2 id="review-title" tabIndex={-1} ref={title}>원문과 대조하기</h2>
      {m > 0 && <p className={css.pos}>아직 안 정한 문장 {m}개</p>}{link && <a className="link" href={back}>{backText}</a>}</div>
  );
  const statusP = <p id="save-status" className={css.status} role="status" aria-atomic="true">{status}</p>;
  if (!ok) return <>{head(0, true)}<div className="paper"><PartFail err={{ code: "", msg: "", ...S.read!.candidates.error }} what="문장 목록" recMissing={w.recMissing} /></div></>;
  if (!scopeReadOk) return <>{head(0, true)}<div className="paper"><PartFail err={{ code: "", msg: "", ...S.read?.[byRec ? "journal" : "questions"]?.error }} what={byRec ? "내 글 목록" : "질문 목록"} recMissing={w.recMissing} /></div></>;
  if (scopePending) return <>{head(0, true)}<div className={`paper ${css.done}`}><b>기록을 확인할 수 없어요.</b>
    <p>이 기록이 현재 목록에 없어 검토가 끝났는지 확인하지 못했어요.</p>
    <div className={css.row}><a className="btn primary" href={back}>{backText}</a></div></div></>;
  if (scopeMissing) return <>{head(0, true)}<div className={`paper ${css.done}`}><b>{byRec ? "이 기록을 찾을 수 없어요." : "이 질문을 찾을 수 없어요."}</b>
    <div className={css.row}><a className="btn primary" href={back}>{backText}</a></div></div></>;
  if (target) return null;
  if (!wait.length) {
    return <>{head(0, false)}<div className={`paper ${css.done}`}><b>아직 안 정한 문장이 없어요.</b>
      <p className={css.scopeDone}>{byRec ? "이 기록의 미결 문장 검토가 끝났어요." : "이 질문의 미결 문장 검토가 끝났어요."}</p><p>{w.emptyHint}</p>
      <div className={css.row}><a className="btn primary" href={back}>{backText}</a><a className="link" href="#structure/cand/confirmed">전체 확정 판단 보기</a></div>{statusP}</div></>;
  }
  if (idx < 0) {   // end — 건너뛰기로 목록 끝에 닿았다
    return <>{head(0, false)}<div className={`paper ${css.done}`}><b>목록 끝이에요. 아직 안 정한 문장 {wait.length}개가 남아 있어요.</b>
      <div className={css.row}><a className="btn primary" href={base + wait[0].id}>남은 문장 보기</a><a className="btn" href={back}>{backText}</a></div>{statusP}</div></>;
  }
  const c = wait[idx], nextId = wait[idx + 1]?.id || "";

  async function decide(c: Cand, action: string, text?: string) {
    const pin = drawn, done = async (msg: string) => {   // 저장됨(또는 충돌) — 상태를 다시 받아 그린다. 못 받으면 문구만 이 자리에
      after.current = { qid, nextId }; flash.current = msg;
      if (!(await ctx.reload())) { after.current = null; flash.current = null; setSay({ text: msg, pin }); setLockS(null); }
    };
    setSay({ text: SAVING, pin }); setLockS(S);
    const body = { candidate_id: c.id, action, ...(Number.isInteger(c.revision) ? { expected_revision: c.revision } : {}), ...(action === "edit_confirm" ? { text } : {}) };
    try {
      await candidateDecide(body, typeof AbortSignal.timeout === "function" ? AbortSignal.timeout(15000) : undefined);
    } catch (e) {
      const er = apiErr(e);
      if (er.code === "UNAUTHORIZED") return;
      if (er.code === "OFFLINE") {   // 응답을 받지 못했다 — 상태를 다시 읽어 이 판단의 결정이 바뀌었는지 본다
        setSay({ text: CHECKING, pin });
        const now = await getJSON<AppState>("/api/state").then(n => (n.candidates || []).find(x => x.id === c.id), () => undefined);
        if (now && now.status !== c.status) return done(w.saved(action));
        setSay({ text: "", err: UNKNOWN, pin }); setLockS(null);
        return;
      }
      if (er.code === "CONFLICT") return done((er.msg || CONFLICT_TEXT) + (action === "edit_confirm" && text !== c.text ? unsavedEdit(text || "") : ""));
      setSay({ text: "", err: er.msg || SAVE_FAIL, pin }); setLockS(null);
      return;
    }
    await done(w.saved(action));
  }
  return (
    <Card key={c.id} S={S} c={c} head={head(wait.length, true)} qText={qText} byRec={byRec} w={w}
      prev={idx > 0 ? base + wait[idx - 1].id : ""} next={base + (nextId || "end")} locked={lockS === S} status={status} err={err}
      onDecide={(a, t) => void decide(c, a, t)} />
  );
}
