// 확인 화면 오류(옛 migErrHtml) — 사람 말 문구(코드는 기술 정보로만). PLAN-STALE 은 바뀐 항목, CHECK-DEPENDENCY 는 가리키는 항목(누르면 그 줄로)
import type { ApiError } from "../../shared/api";
import { mdhm } from "../../shared/date";
import { postMsg } from "../../shared/postErr";
import { Tech } from "../../shared/Tech";
import type { PItem } from "./migApi";
import { MIG_ACT, MIG_STATE } from "./text";
import { Why } from "./Why";
import css from "./Migration.module.css";

type Chg = { seq: number; sealed: string; now: string; reason?: string | null };
const AGAIN = "아래 [이 plan 취소]로 취소한 뒤 PC에서 다시 올려 주세요.";

export function MigErr({ e, items }: { e: ApiError; items: PItem[] }) {
  const j = e.j || {}, d = (j.detail || {}) as { changed?: Chg[]; needed?: number; seqs?: number[]; state?: string };
  const name = (s: number) => { const x = items.find(i => i.seq === s); return `#${s} ${x && x.title ? x.title : ""}`; };
  const box = (b: string, more?: React.ReactNode) => <div className="partfail"><b>{b}</b>{more}{e.code ? <Tech err={{ code: e.code, msg: String(j.msg || "") }} /> : null}</div>;
  const jump = (s: number) => (ev: React.MouseEvent) => { ev.preventDefault(); document.getElementById(`mig-i-${s}`)?.scrollIntoView?.({ block: "center" }); };
  switch (e.code) {
    case "PLAN-STALE": return box("확인한 뒤 서버 자료가 바뀌어 반영 결과가 달라졌어요. 아무것도 반영하지 않았어요.",
      <><ul className={css.chg}>{(d.changed || []).map(c => <li key={c.seq}>{`${name(c.seq)}: ${MIG_ACT[c.sealed] || c.sealed} → ${MIG_ACT[c.now] || c.now}`}{c.reason ? <>, <Why r={c.reason} /></> : null}</li>)}</ul><p>{AGAIN}</p></>);
    case "PLAN-HASH-MISMATCH": return box("확인한 plan과 서버에 저장한 plan이 달라요. 아무것도 반영하지 않았어요.", <p>{AGAIN}</p>);
    case "RATE-LIMIT": return box(`오늘 남은 이관 한도보다 새로 넣을 행이 많아요${d.needed != null ? `(${d.needed}행)` : ""}. 아무것도 반영하지 않았어요.`,
      <p>{j.resume_at ? `${mdhm(String(j.resume_at))} 이후에` : "내일"} 다시 반영해 주세요.</p>);
    case "PLAN-EXPIRED": return box("보관 기간(3일)이 지나 이 plan이 닫혔어요. 올린 본문은 지웠어요.", <p>PC에서 다시 올려 주세요.</p>);
    case "CHECK-DEPENDENCY": return box("체크하지 않은 기준을 가리키는 항목이 있어요. 아무것도 반영하지 않았어요.",
      <><ul className={css.chg}>{(d.seqs || []).map(s => <li key={s}><a href={location.hash} onClick={jump(s)}>{name(s)}</a></li>)}</ul>
        <p>그 항목이 가리키는 기준을 체크하거나, 이 plan을 취소한 뒤 그 항목을 빼고 다시 올려 주세요.</p></>);
    case "PLAN-STATE": return box(`지금 plan 상태(${(MIG_STATE[d.state || ""] || ["", d.state])[1]})에선 할 수 없어요. 다시 불러왔어요.`);
    case "MIGRATION-OFF": return box("지금은 이관이 꺼져 있어요. 운영자가 켠 뒤 다시 해 주세요.");
    case "MIGRATION-NOT-ALLOWED": return box("이 계정은 이관 허용 목록에 없어요. 운영자에게 넣어 달라고 하세요.");
    default: return box(postMsg(e));
  }
}
