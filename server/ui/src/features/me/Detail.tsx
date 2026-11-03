// 데이터 한 건의 상세 — 종류별(내 글·질문·판단·항목·읽고 든 생각). lens = 「나」 렌즈 이름(항목만 — 그래프 + 옆 묶음)
import { mdhm } from "../../shared/date";
import { CandDetail } from "./CandDetail";
import { Conn } from "./Conn";
import { Head } from "./Head";
import { ItemDetail } from "./ItemDetail";
import type { Row, World } from "./model";
import { RecDetail } from "./RecDetail";
import { ReflDetail } from "./ReflDetail";

export function Detail({ W, r, lens, trashOn }: { W: World; r: Row; lens?: string; trashOn: boolean }) {
  if (r.k === "journal") return <RecDetail W={W} id={r.id} x={r.x} trashOn={trashOn} />;
  if (r.k === "q") return <><Head kind="질문" title={r.x.text} meta={mdhm(r.at)} /><Conn W={W} kind="q" id={r.id} /></>;
  if (r.k === "cand") return <CandDetail W={W} r={r} trashOn={trashOn} />;
  if (r.k === "item") return <ItemDetail W={W} r={r} lens={lens} trashOn={trashOn} />;
  return <ReflDetail W={W} r={r} trashOn={trashOn} />;
}
