// 탭 보기 — 목록 | 가운데(고른 데이터) | 옆 묶음(렌즈 탭만). 1열 = 목록 또는 상세 하나. 렌즈 = 기준·결정 근거 역추적 · 축 묶음 · 사람 관계
import { Back } from "./Back";
import { Detail } from "./Detail";
import { Groups } from "./Groups";
import { edges } from "./links";
import { MeList } from "./MeList";
import { homeRows, type TabRow, type World } from "./model";
import { PersonCenter } from "./PersonCenter";
import { SourceCenter } from "./SourceCenter";
import { GONE, ME_LENS, type MeTab } from "./text";
import type { useWorld } from "./useWorld";
import { useMobile } from "./view";
import type { Person, Source } from "../../shared/state";
import css from "./Me.module.css";

type Props = { W: World; t: MeTab; rows: TabRow[]; sel: TabRow | null; want: string; trashOn: boolean;
  recs: ReturnType<typeof useWorld>["recs"]; person: { state: "ok" | "loading" | "fail"; retry: () => void } };

function Center({ W, t, sel, trashOn, recs, person }: Omit<Props, "rows" | "want"> & { sel: TabRow }) {
  if (t === "person") return <PersonCenter W={W} p={sel.x as Person} state={person.state} retry={person.retry} />;
  if (t === "source") return <SourceCenter W={W} x={sel.x as Source} recs={recs} />;
  const r = homeRows(W).find(x => x.k === "item" && x.id === sel.id);
  return r ? <Detail W={W} r={r} lens={ME_LENS[t]} trashOn={trashOn} /> : <div className="empty">{GONE} <a href="#_me">목록으로</a></div>;
}

export function LensView(p: Props) {
  const { W, t, rows, sel, want } = p, mobile = useMobile(), lens = !!ME_LENS[t];
  const showList = !mobile || !want, showDetail = !mobile || !!want;
  const title = t === "axis" ? "이 축에 묶인 데이터" : t === "person" ? "이 사람과의 관계" : "근거·연결";
  return (
    <div className={`${css.lens}${lens ? " " + css.three : ""}`}>
      {showList && <MeList W={W} tab={t} rows={rows} sel={sel} />}
      {showDetail && <section className={`paper hdetail ${css.center}`} id="home-detail" aria-live="polite">
        <Back to={`#_me/${t}`} label="목록" />
        {want && !sel ? <div className="empty">{GONE} <a href="#_me">목록으로</a></div> : sel ? <Center {...p} sel={sel} /> : null}
      </section>}
      {showDetail && lens && sel && <Groups W={W} all={t === "person" ? edges(W, "person", sel.id) : edges(W, "item", sel.id)} title={title} self={t === "person" ? sel.id : ""} />}
    </div>
  );
}
