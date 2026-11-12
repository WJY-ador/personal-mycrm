// 대시보드 껍데기 — 라우터(hash) · 상태 한 벌(/api/state) · 탭 줄 · Setup 줄 · 띠 · 화면 하나 · 상시 섬 · 미저장 보호 · 결과 한 줄.
// app.html 은 정적 뼈대(서버가 역할 구간을 strip)만 — 이 앱은 #view 에 뜨고, 뼈대의 다른 자리(#nav-tabs·#subnav·#bands·#ui-mast·#ui-desk·#foot)엔 포털로 그린다.
import { Suspense, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { ChatRoot } from "../features/chat/ChatRoot";
import { DeskDialog } from "../features/desk/DeskDialog";
import { Mast } from "../features/mast/Mast";
import { NameDialog } from "../features/name/NameDialog";
import { WebchatRoot } from "../features/webchat/WebchatRoot";
import type { UiCtx } from "../shared/ctx";
import { mdhm } from "../shared/date";
import { PartFail } from "../shared/PartFail";
import { needName, resolve, type View } from "../shared/route";
import { readOk } from "../shared/state";
import { LOADING as LOADING_TEXT } from "../shared/words";
import { OfflineBand, TabsBand } from "./Bands";
import { LeaveDialog } from "./LeaveDialog";
import { SCREENS } from "./registry";
import { SetupNav } from "./SetupNav";
import { UpdateBand } from "./UpdateBand";
import { Tabs } from "./Tabs";
import { reload, reloadState, useAppState, useAutoRefresh } from "./useAppState";
import { useHash } from "./useHash";
import { useHeader } from "./useHeader";

const LOADING = <p className="hint">{LOADING_TEXT}</p>;
const at = (id: string, node: ReactNode) => { const el = document.getElementById(id); return el ? createPortal(node, el) : null; };
type Shown = Exclude<View, { replace: string }>;
const isShown = (v: View | null): v is Shown => !!v && "tab" in v;

export function App() {
  const { S, failed, revision } = useAppState();
  // 미저장 보호 — 옮긴 화면이 ctx.setDirty 로 알린 「고치던 글이 있는 주소」. 다른 주소로 가면 그 자리로 되돌리고 묻는다
  const dirty = useRef<string | null>(null), leaveTo = useRef("");
  const [leave, setLeave] = useState(false);
  const guard = useCallback(() => {
    const d = dirty.current;
    if (!d || location.hash === d) return false;
    leaveTo.current = location.hash;
    history.pushState(null, "", d);
    setLeave(true);
    return true;
  }, []);
  const hash = useHash(guard);
  const autoRefreshDirtyChanged = useAutoRefresh(!!S, dirty, revision);
  const setDirty = useCallback((h: string | null) => {
    dirty.current = h;
    autoRefreshDirtyChanged(h !== null);
  }, [autoRefreshDirtyChanged]);

  // 결과 한 줄 — done(문구, 주소?) 뒤 상태를 다시 받고, 그 주소의 화면에 한 번(ctx.flash). 다른 주소로 가면 사라진다
  const [flash, setFlash] = useState<{ text: string; at: string } | null>(null);
  const done = useCallback(async (text: string, h?: string) => {
    if (h != null) history.replaceState(null, "", h);
    await reload();
    setFlash({ text, at: location.hash });
  }, []);
  useEffect(() => { setFlash(f => (f && f.at !== hash ? null : f)); }, [hash]);
  const shownFlash = flash && flash.at === hash ? flash : null;

  // 대화창(표시 이름 · 문의) — 열 때마다 새 ctx(args[0] = 어디로). 상태는 연 때의 것
  const [nameReq, setNameReq] = useState(0), [desk, setDesk] = useState({ where: "", n: 0 });
  const openName = useCallback(() => setNameReq(n => n + 1), []);
  const openDesk = useCallback((where: string) => { if (document.getElementById("ui-desk")) setDesk(d => ({ where, n: d.n + 1 })); }, []);
  useHeader({ S, reload: reloadState, openName, openDesk, dirty });
  const sRef = useRef(S);
  sRef.current = S;
  const nameCtx = useMemo<UiCtx>(() => ({ reload, done, state: sRef.current || undefined, args: nameReq ? ["open"] : [] }), [nameReq, done]);
  const deskCtx = useMemo<UiCtx>(() => ({ reload, done, state: sRef.current || undefined, args: desk.n ? [desk.where] : [] }), [desk, done]);
  const island = useMemo<UiCtx>(() => ({ reload, state: S || undefined }), [S]);

  // 판정(주소 + 상태) — 옛 주소는 replace(그동안은 앞 화면 그대로) · 판단 검토의 돌아갈 곳 = 탭마다 마지막으로 본 주소
  const lastView = useRef<Record<string, string>>({}), lastShown = useRef<Shown | null>(null);
  const gate = !!S && needName(S);
  const view = S && !gate ? resolve(hash, S, lastView.current) : null;
  const replaceTo = view && !isShown(view) ? view.replace : "";
  useLayoutEffect(() => { if (replaceTo) location.replace(replaceTo); }, [replaceTo]);
  const shown: Shown | null = isShown(view) ? view : lastShown.current;
  useEffect(() => {
    if (isShown(view)) { lastShown.current = view; if (view.remember) lastView.current[view.tab.id] = hash || "#" + view.tab.id; }
  });
  useEffect(() => { document.body.classList.toggle("navnew-screen", !gate && !!shown?.navnew); }, [gate, shown?.navnew]);

  const args = gate ? [] : shown?.args || [];
  const argsKey = args.join("\u0000");
  const ctx = useMemo<UiCtx>(() => ({ reload, done, setDirty, state: S || undefined, args, flash: shownFlash }),
    [S, argsKey, shownFlash, done, setDirty]);   // args 는 argsKey(글자)로 본다 — 같은 주소면 같은 ctx

  if (!S) return failed ? at("bands", <OfflineBand loadedAt="" />) : LOADING;
  const metaOk = readOk(S, "meta"), loadedAt = mdhm(S.generated);
  const name = gate ? "name" : shown?.screen || "";
  const Screen = SCREENS[name];
  const body = !gate && !metaOk
    ? <div className="paper"><PartFail err={S.read?.meta?.error || { code: "", msg: "" }} what="이 데이터 폴더" /></div>
    : Screen ? <Suspense fallback={LOADING}><Screen ctx={ctx} /></Suspense> : null;
  const band = failed ? <OfflineBand loadedAt={loadedAt} /> : !gate && metaOk && !readOk(S, "tabs") ? <TabsBand S={S} /> : null;
  return (
    <>
      {at("nav-tabs", gate ? null : <Tabs S={S} cur={shown?.cur || ""} />)}
      <SetupNav S={S} cur={gate || !metaOk ? null : shown?.setup ?? null} />
      {at("bands", <>{band}<UpdateBand /></>)}
      {body}
      {at("ui-mast", gate ? null : <Mast ctx={island} />)}
      {at("foot", gate ? "표시 이름을 정하면 대시보드가 열려요." : loadedAt ? `불러온 시각 ${loadedAt}.` : "")}
      {/* AI 하나로 A2: 웹 AI가 켜져 있으면 옛 정리 서랍(features/chat)은 버튼, 안내, 서랍을 통째로 그리지 않는다. 꺼져 있으면 그대로 */}
      {gate || S.switches?.webchat ? null : <ChatRoot ctx={island} />}
      {gate || !S.switches?.webchat ? null : <WebchatRoot ctx={island} />}
      <NameDialog ctx={nameCtx} />
      {at("ui-desk", <DeskDialog ctx={deskCtx} />)}
      <LeaveDialog open={leave}
        stay={() => { setLeave(false); document.getElementById("hedit-input")?.focus(); }}
        go={() => { setLeave(false); setDirty(null); const to = leaveTo.current; leaveTo.current = ""; location.hash = to || "#_me"; }} />
    </>
  );
}
