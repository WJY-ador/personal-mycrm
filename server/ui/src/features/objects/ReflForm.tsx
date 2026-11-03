// 읽고 든 생각 쓰기·고치기 폼(옛 reflForm · refl-new·refl-edit) — 출처 · 유형(내 요약|내 반응) · 본문. 본문 곁 안내만(확인 체크 없음).
// 새로 쓰면 확인 전으로 들어가고, 확인했어요 상태를 고치면 확인 전으로 돌아간다(서버 판정 — 결과 문구는 응답 review 로)
import type { FormEvent } from "react";
import type { Refl } from "../../shared/state";
import { srcName } from "./model";
import { objApi } from "./objApi";
import type { P } from "./props";
import { REFL_HELP, REFL_KIND } from "./text";
import { useWrite } from "./useWrite";

export function ReflForm({ ctx, S, x, sid = "" }: P & { x?: Refl; sid?: string }) {
  const w = useWrite(ctx), srcs = S.sources || [];
  if (!srcs.length) return <div className="empty">먼저 출처를 만들어요. <a className="link" href="#_obj/source">출처 추가하기</a></div>;
  const fid = x ? "refl-edit" : "refl-new";
  async function save(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = e.currentTarget, d = new FormData(f);
    const body = { source_id: String(d.get("source_id") || ""), kind: String(d.get("kind") || ""), body: String(d.get("body") || "") };
    if (!body.body.trim()) return w.setErr(fid, "본문을 적어 주세요.");
    if (!body.kind) return w.setErr(fid, "내 요약·내 반응 중 하나를 골라 주세요.");
    if (!x) { if (await w.go(fid, () => objApi.reflNew(body), () => ["확인 전으로 저장했어요.", `#_obj/source/${body.source_id}`])) f.reset(); return; }
    await w.go(fid, () => objApi.reflEdit(x.id, { ...body, expected_revision: x.revision }),
      j => [j?.review === "pending" && x.review === "reviewed" ? "고쳤어요. 확인 전으로 돌아갔어요." : "고쳤어요."]);
  }
  return (
    <form className="fform" noValidate onSubmit={save} key={x ? `${x.id}:${x.revision}` : sid}>
      <label htmlFor={`${fid}-src`}>출처</label>
      <select id={`${fid}-src`} name="source_id" defaultValue={x ? x.source_id : sid}>{srcs.map(s => <option key={s.id} value={s.id}>{srcName(S, s.id)}</option>)}</select>
      <fieldset><legend>유형</legend>{Object.entries(REFL_KIND).map(([k, l]) => <label key={k}><input type="radio" name="kind" value={k} defaultChecked={x?.kind === k} /> {l}</label>)}</fieldset>
      <label htmlFor={`${fid}-body`}>본문</label>
      <p className="fnote" id={`${fid}-help`}>{REFL_HELP}</p>
      <textarea id={`${fid}-body`} name="body" rows={6} aria-describedby={`${fid}-help`} defaultValue={x ? x.body : ""} />
      {x && x.review === "reviewed" ? <p className="fnote">고치면 확인 전으로 돌아가요.</p>
        : x ? null : <p className="hint">저장하면 확인 전으로 들어가요. 「확인했어요」는 판단 확정이 아니고 근거로 인용하지 않아요.</p>}
      <div className="frow"><button className="primary" type="submit" disabled={w.busy}>{x ? "고친 내용 저장" : "저장"}</button></div>
      <p className="ferr" role="alert" aria-atomic="true">{w.errOf(fid)}</p>
    </form>
  );
}
