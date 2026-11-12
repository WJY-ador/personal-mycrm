// 활동 줄(옛 actRow) — 행동 칩 · 날짜(없으면 「날짜 미확인」) + 출처 · 사람(역할) · 축 · 메모 수 · 철회. 「나」 문맥·활동 목록이 같이 쓴다.
// 줄만 그린다(<li>) — 목록 상자(<ul class="rows">)·빈 문구는 부르는 쪽이 정한다(더 보기로 이어 붙이는 목록).
import { dOnly } from "./date";
import { actLabel, ROLE_LABEL, type Act } from "./activity";

export function ActRow({ a, actions }: { a: Act; actions?: Record<string, string> }) {
  const when = a.occurred_on ? dOnly(a.occurred_on) : `날짜 미확인${a.observed_on ? `, 처음 수집 ${dOnly(a.observed_on)}` : ""}`;
  const people = (a.people || []).map((p, i) => <span key={p.id}>{i ? ", " : ""}{p.alias}<span className="tech"> {ROLE_LABEL[p.role || ""] || p.role}</span></span>);
  const rest = [(a.axes || []).map(x => x.title || "(제목 없음)").join(", "), a.memo_count ? `메모 ${a.memo_count}` : "", a.state === "retracted" ? "철회됨" : ""];
  const parts = [a.source?.name || "", people.length ? people : "", ...rest].filter(x => x !== "" && !(Array.isArray(x) && !x.length));
  return (
    <li className="actrow">
      <a href={`#_obj/activity/${a.id}`}><span className="chip">{actLabel(actions, a.action)}</span><span className={`when${a.occurred_on ? "" : " undated"}`}>{when}</span></a>
      {parts.length > 0 && <span className="meta">{parts.map((x, i) => <span key={i}>{i ? ", " : ""}{x}</span>)}</span>}
    </li>
  );
}

// 줄 목록 — 비었으면 empty 문구(없으면 아무것도 안 그림)
export function ActRows({ xs, actions, empty = "" }: { xs: Act[]; actions?: Record<string, string>; empty?: string }) {
  if (!xs.length) return empty ? <div className="empty">{empty}</div> : null;
  return <ul className="rows">{xs.map(a => <ActRow key={a.id} a={a} actions={actions} />)}</ul>;
}
