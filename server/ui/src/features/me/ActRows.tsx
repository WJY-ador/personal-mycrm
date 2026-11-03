// 활동 줄(옛 actRow — 활동 화면 R4 까지 일시 중복) — 행동 칩 · 날짜(없으면 「날짜 미확인」) + 출처 · 사람 · 축 · 메모 수 · 철회
import { dOnly } from "../../shared/date";
import type { Act } from "./meApi";
import type { World } from "./model";

const ROLE: Record<string, string> = { author: "글쓴이", counterparty: "상대", participant: "참여자" };

export function ActRows({ W, xs }: { W: World; xs: Act[] }) {
  if (!xs.length) return null;
  return (
    <ul className="rows">{xs.map(a => {
      const when = a.occurred_on ? dOnly(a.occurred_on) : `날짜 미확인${a.observed_on ? ` · 처음 수집 ${dOnly(a.observed_on)}` : ""}`;
      const people = (a.people || []).map((p, i) => <span key={p.id}>{i ? ", " : ""}{p.alias}<span className="tech"> {ROLE[p.role || ""] || p.role}</span></span>);
      const rest = [(a.axes || []).map(x => x.title || "(제목 없음)").join(", "), a.memo_count ? `메모 ${a.memo_count}` : "", a.state === "retracted" ? "철회됨" : ""];
      const parts = [a.source?.name || "", people.length ? people : "", ...rest].filter(x => x !== "" && !(Array.isArray(x) && !x.length));
      return (
        <li className="actrow" key={a.id}>
          <a href={`#_obj/activity/${a.id}`}><span className="chip">{W.S.activity_ui?.actions?.[a.action] || a.action}</span><span className={`when${a.occurred_on ? "" : " undated"}`}>{when}</span></a>
          {parts.length > 0 && <span className="meta">{parts.map((x, i) => <span key={i}>{i ? " · " : ""}{x}</span>)}</span>}
        </li>
      );
    })}</ul>
  );
}
