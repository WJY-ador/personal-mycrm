// 마스트(옛 mast) — 오늘 스펙트럼(확정한 판단 · 아직 안 정함 · 반영 안 함 · 판단이 없는 글, 비율 = 개수) + 질문 레전드(미결정 수 · [한 장]).
// 껍데기 머리글 .axiswrap 자리(#ui-mast)의 상시 섬. 날짜·계정 메뉴는 껍데기 몫. 새 탐색 화면에선 CSS 가 숨긴다(body.navnew-screen).
import type { ScreenProps } from "../../shared/ctx";
import { clip, NO_QUESTION } from "../../shared/clip";
import { readOk } from "../../shared/state";
import { qTabId } from "../../shared/tabs";

export function Mast({ ctx }: ScreenProps) {
  const S = ctx.state!;
  const cs = readOk(S, "candidates") ? S.candidates || [] : [], js = readOk(S, "journal") ? S.journal || [] : [];
  const used = new Set(cs.map(c => c.record_id));
  const parts: [string, number, string][] = [["확정한 판단", cs.filter(c => c.status === "confirmed").length, "--mine"],
    ["아직 안 정함", cs.filter(c => c.status === "pending").length, "--warn"],
    ["반영 안 함", cs.filter(c => c.status === "excluded").length, "--soft"],
    ["판단이 없는 글", js.filter(j => !used.has(j.id)).length, "--line"]];
  const total = parts.reduce((s, p) => s + p[1], 0), sum = parts.map(p => `${p[0]} ${p[1]}`).join(", ");
  const qs = readOk(S, "questions") ? S.questions || [] : [], qTab = qTabId(S);
  const wait = (qid: string | null) => (S.candidates || []).filter(c => c.question_id === qid && c.status === "pending").length;
  const nq = readOk(S, "candidates") ? (S.candidates || []).filter(c => !c.question_id && c.status === "pending").length : 0;
  return (
    <>
      <div className="axistop" id="axistop" hidden={!total}><span className="speclabel">오늘</span><div className="specbox">
        <div className="spectrum" id="spectrum" role="img" title={sum} aria-label={sum}>{parts.filter(p => p[1]).map(p =>
          <div key={p[0]} style={{ flex: p[1], background: `var(${p[2]})` }} title={`${p[0]} ${p[1]}`} />)}</div>
        <div className="speckey" id="speckey">{parts.map(p => <span key={p[0]}><i style={{ background: `var(${p[2]})` }} />{`${p[0]} ${p[1]}`}</span>)}</div></div></div>
      <div className="axislegend" id="legend">{qs.length ? qs.map((q, i) => {
        const m = wait(q.id);
        return (
          <span className="ax" key={q.id}><b>Q{i + 1}</b><span title={q.text}>{clip(q.text, 30)}</span><em className={m ? "on" : ""}>미결정 {m}</em>
            <button className="axpage" type="button" onClick={() => { location.hash = `#${qTab}/${q.id}`; }}>한 장</button></span>
        );
      }) : <span className="ax">질문이 아직 없어요</span>}
        {nq ? <span className="ax"><b>—</b><span>{NO_QUESTION}</span><em className="on">미결정 {nq}</em></span> : null}</div>
    </>
  );
}
