// 공존 다리(R1~R5) — 옛 app.html 라우터가 옮긴 화면을 CrmUI.mount 로 띄우고 unmount 로 내린다. R5 에서 지운다.
import { createRoot, type Root } from "react-dom/client";
import { QueryClientProvider } from "@tanstack/react-query";
import { SCREENS } from "./layout/registry";
import { queryClient } from "./shared/queries";
import type { UiCtx } from "./shared/ctx";

type Bridge = { mount: typeof mount; unmount: typeof unmount };
declare global {
  interface Window { CrmUI?: Bridge; CrmUIPending?: [string, HTMLElement, UiCtx] }
}
const slots = new Map<string, { el: HTMLElement; root: Root }>();

// 같은 화면·같은 자리에 다시 오면 새 ctx 로 다시 그리기만 한다(화면 안 문구·더 받은 쪽 유지)
function mount(name: string, el: HTMLElement, ctx: UiCtx): void {
  const Screen = SCREENS[name];
  if (!Screen) throw new Error(`옮긴 화면이 아니에요: ${name}`);
  let s = slots.get(name);
  if (s && s.el !== el) unmount(name);
  s = slots.get(name);
  if (!s) slots.set(name, (s = { el, root: createRoot(el) }));
  s.root.render(
    <QueryClientProvider client={queryClient}>
      <Screen ctx={ctx} />
    </QueryClientProvider>,
  );
}

function unmount(name: string): void {
  slots.get(name)?.root.unmount();
  slots.delete(name);
}

// 옛 껍데기가 새 상태(S)를 받았다 — 서버 조회를 다시 받는다(옛 화면이 상태마다 목록을 다시 받던 것과 같다)
window.addEventListener("crm:state", () => void queryClient.invalidateQueries());
window.CrmUI = { mount, unmount };
// 이 모듈보다 옛 라우터가 먼저 화면을 고른 경우 — 맡겨 둔 자리가 아직 화면에 있으면 띄운다
const p = window.CrmUIPending;
window.CrmUIPending = undefined;
if (p && p[1].isConnected) mount(...p);
