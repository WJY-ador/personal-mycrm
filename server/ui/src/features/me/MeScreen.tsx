// 「나」(#_me) — 머리(표시 이름) · 하위 탭(고정 6 + 사용자 오브젝트마다 하나, 순서 = 레이아웃) · 축 띠 · 탭 보기(목록 | 가운데 | 옆 묶음) 또는 요약(레이아웃 블록).
// 라우트 #_me/<탭>[/<id>] · 오브젝트 탭 #_me/obj/<key>[/<id>](목록 보기 | 항목 페이지) · 옛 #_me/<journal|q|cand|refl>/<id> = 그 데이터 상세(하위 탭 줄 아래 단독)
// · #_me/item/<id> → 그 항목의 탭(replace) · 옛 #_me/custom[/<id>] → 그 항목의 오브젝트 탭(없으면 첫 오브젝트 탭)(replace).
// 쓰기 = 상세의 동작 버튼·인라인 편집([저장])뿐. 연결 = 저장된 관계만(추정 0). 고른 데이터는 주소(hash)에만 남는다.
import { useEffect, useLayoutEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import type { ScreenProps } from "../../shared/ctx";
import { Back } from "./Back";
import { AxisBand } from "./AxisBand";
import { Detail } from "./Detail";
import { EditCtx, useEditStore } from "../../shared/edit";
import { LensView } from "./LensView";
import { pick } from "./links";
import { meApi, type MePage } from "./meApi";
import { customDefs, homeRows, itemById, objDefByKey, srcById, tabOfItem, tabRows } from "./model";
import { ObjTab } from "./obj/ObjTab";
import { NameHead } from "./NameHead";
import { RecDetail } from "./RecDetail";
import { SubTabs, tabHref } from "./SubTabs";
import { Summary } from "./summary/Summary";
import type { Blocks } from "./summary/block";
import { GONE, ME_EMPTY, OBJ_TAB, OBJ_TEXT, URL_KINDS, fitTabs, isTab, objTabKey, validTabs } from "./text";
import { axisCtx, QK, useWorld } from "./useWorld";
import { isAxis } from "./Conn";
import { backNav, useMobile, useViewStore, ViewCtx } from "./view";
import css from "./Me.module.css";

const here = () => location.hash || "#_me";

type Props = ScreenProps & { blocks: Blocks; layoutDefault: MePage };

export function MeScreen({ ctx, blocks, layoutDefault }: Props) {
  const S = ctx.state!, [a = "", b = "", c = ""] = ctx.args || [];
  const { W, statsFail, recs } = useWorld(S);
  const lay = useQuery({ queryKey: QK.layout, queryFn: meApi.layout });
  const page = lay.data?.layout?.pages?.me, L = page && validTabs(page.tabs) ? page : layoutDefault;
  const tabs = fitTabs(L.tabs, customDefs(W).map(d => d.key)), mobile = useMobile();
  const solo = URL_KINDS.includes(a) && !!b;
  const t = a === "obj" ? OBJ_TAB + b : isTab(a) ? a : tabs[0];
  const ft = isTab(t) && t !== "summary" && !solo ? t : null;   // 고정 탭 목록(오브젝트 탭은 목록 보기 — 연결 수 고르기 없음)
  const rows = ft ? tabRows(W, ft) : [];
  const sel = !ft || (mobile && !b) ? null : pick(W, ft, rows, b);   // 1열 첫 진입 = 목록만
  const selItem = !solo && sel && t !== "person" && t !== "source" && isAxis(W, sel.id) ? sel.id : "";
  useQuery({ queryKey: QK.axis(selItem), queryFn: () => axisCtx(selItem), enabled: !!selItem });
  const pid = !solo && t === "person" && sel ? sel.id : "";
  const pq = useQuery({ queryKey: QK.person(pid), queryFn: () => meApi.person(pid), enabled: !!pid });
  const it = a === "item" && b ? itemById(W, b) : undefined;
  const old = a === "custom" && b ? itemById(W, b) : undefined;
  const redirect = a && !b && srcById(W, a) ? "#_obj/source/" + a   // 옛 「나」 홈 출처 고르기 링크
    : it && it.revision ? `#_me/${tabOfItem(W, it)}/${encodeURIComponent(b)}`
    : old && old.revision ? `#_me/${tabOfItem(W, old)}/${encodeURIComponent(b)}`   // 옛 커스텀 탭 항목 = 그 오브젝트 탭
    : a === "custom" ? (tabs.find(x => objTabKey(x)) ? tabHref(tabs.find(x => objTabKey(x))!) : "#_me")
    : a && a !== "obj" && !solo && !isTab(a) ? tabHref(t)
    : !a && !isTab(t) ? tabHref(t)   // 첫 탭이 오브젝트 탭
    : ft && !b && sel ? `#_me/${t}/${encodeURIComponent(sel.id)}` : "";   // 넓은 화면 진입 = 연결 최다 — 주소에 남긴다
  useLayoutEffect(() => { if (redirect) location.replace(redirect); }, [redirect]);
  const center = solo || (a === "obj" && c) ? here() : sel ? `#_me/${t}/${sel.id}` : "";
  // 껍데기가 아직 이 주소를 그리지 않았거나(내가 방금 replace) 이번에 replace 하는 중이면 결과 문구를 「보였다」고 치지 않는다
  const settled = !redirect && here() === (a ? `#_me/${a}${b ? "/" + b : ""}${c ? "/" + c : ""}` : "#_me");
  const edit = useEditStore(ctx, !settled, "#_me"), view = useViewStore(center);
  const open = a === "obj" ? c : b;   // 1열 목록으로 돌아오면 그 자리로
  useEffect(() => { if (mobile && !open && !solo && backNav.y) { window.scrollTo(0, backNav.y); backNav.y = 0; } }, [mobile, open, solo]);
  if (redirect) return null;
  const trashOn = !!S.switches?.trash;
  let body;
  if (solo) {
    const r = homeRows(W).find(x => x.k === a && x.id === b);
    body = <section className={`paper hdetail ${css.solo}`} id="home-detail" aria-live="polite"><Back to="#_me" label="돌아가기" />
      {r ? <Detail W={W} r={r} trashOn={trashOn} /> : a === "journal" ? <RecDetail W={W} id={b} x={undefined} trashOn={trashOn} />
        : <div className="empty">{GONE} <a href="#_me">목록으로</a></div>}</section>;
  } else if (a === "obj") {
    const d = objDefByKey(W, b);
    body = d ? <ObjTab key={d.key} W={W} def={d} id={c} trashOn={trashOn} /> : <div className="paper"><div className="empty">{OBJ_TEXT.gone} <a href="#_me">{OBJ_TEXT.back}</a></div></div>;
  } else if (t === "summary") body = <Summary W={W} slots={L.regions.summary || []} blocks={blocks} statsFail={statsFail} />;
  else if (!rows.length) body = <div className="paper"><div className="empty">{ME_EMPTY}</div></div>;
  else body = <LensView W={W} t={ft!} rows={rows} sel={sel} want={b} trashOn={trashOn} recs={recs}
    person={{ state: pq.isError ? "fail" : pq.data ? "ok" : "loading", retry: () => void pq.refetch() }} />;
  return (
    <EditCtx.Provider value={edit}>
      <ViewCtx.Provider value={view}>
        <NameHead name={S.user?.display_name || ""} />
        <SubTabs W={W} tabs={tabs} cur={solo ? "" : t} />
        {!solo && <AxisBand W={W} sel={t === "axis" && sel ? sel.id : ""} fail={statsFail} />}
        {body}
      </ViewCtx.Provider>
    </EditCtx.Provider>
  );
}
