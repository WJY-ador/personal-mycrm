// revision 기반 자동 갱신(useAutoRefresh) 합성 시험 — 가짜 fetch · 가짜 setInterval. 서버·DB 연결 없음.
import { act, useRef } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClientProvider, useQuery } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { queryClient } from "../shared/queries";
import { calls, flush, installFetch, json, serve } from "../test/fakeServer";
import { useAutoRefresh } from "./useAppState";

let roots: Root[] = [];
let listCalls = 0;
const markers = () => calls.filter(c => c.url === "/api/state/revision").length;

function List() {
  useQuery({ queryKey: ["hook-list"], queryFn: async () => { listCalls++; return (await fetch("/api/list")).json() as Promise<unknown>; } });
  return null;
}
type ProbeProps = { revision: number | null; dirty?: string | null; onUnauthorized?: () => void; expose?: (f: (d: boolean) => void, ref: { current: string | null }) => void };
function Probe({ revision, dirty = null, onUnauthorized, expose }: ProbeProps) {
  const ref = useRef<string | null>(dirty);
  const changed = useAutoRefresh(true, ref, revision, { onUnauthorized });
  expose?.(changed, ref);
  return null;
}
async function mount(node: React.ReactNode) {
  const el = document.createElement("div");
  document.body.append(el);
  const root = createRoot(el);
  roots.push(root);
  const render = (n: React.ReactNode) => root.render(<QueryClientProvider client={queryClient}>{n}</QueryClientProvider>);
  await act(async () => { render(node); });
  await flush();
  return { root, render };
}
async function tick() {
  await act(async () => { await vi.advanceTimersByTimeAsync(30_000); });
  for (let i = 0; i < 3; i++) await flush();
}

beforeEach(() => {
  installFetch(); queryClient.clear(); listCalls = 0;
  vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
});
afterEach(() => {
  for (const r of roots) act(() => r.unmount());
  roots = [];
  vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals();
});

test("표지 실패(503·연결 실패·형식 이상)는 조용히 넘기고 다음 tick에 다시 물어 바뀐 표지면 다시 받는다", async () => {
  const replies: Array<() => Response | Promise<Response>> = [
    () => json(503, {}),
    () => Promise.reject(new TypeError("offline")),
    () => json(200, { revision: "2" }),
    () => new Response("not json", { status: 200 }),
    () => json(200, { revision: 2 }),
  ];
  let n = 0;
  serve(url => url === "/api/state/revision" ? replies[n++]() : json(200, { ok: true }));
  await mount(<><List /><Probe revision={1} /></>);
  expect(listCalls).toBe(1);
  for (let i = 1; i <= 4; i++) {
    await tick();
    expect({ i, markers: markers(), listCalls }).toEqual({ i, markers: i, listCalls: 1 });
  }
  await tick();
  expect({ markers: markers(), listCalls }).toEqual({ markers: 5, listCalls: 2 });
});

test("진행 중인 조회가 있으면 바뀐 표지를 보류하고 취소하지 않으며 QueryCache가 한가해지면 한 번만 다시 받는다", async () => {
  let finishSlow!: (r: Response) => void, slowSignal: AbortSignal | undefined, slowCalls = 0;
  serve(url => {
    if (url === "/api/state/revision") return json(200, { revision: 2 });
    if (url === "/api/slow") return slowCalls === 1 ? new Promise<Response>(r => { finishSlow = r; }) : json(200, "다시");
    return json(200, { ok: true });
  });
  function Slow() {
    useQuery({ queryKey: ["hook-slow"], queryFn: ({ signal }) => { slowCalls++; slowSignal ??= signal; return fetch("/api/slow", { signal }).then(r => r.json() as Promise<string>); } });
    return null;
  }
  await mount(<><List /><Slow /><Probe revision={1} /></>);
  expect(queryClient.isFetching()).toBe(1);
  await tick();
  expect({ markers: markers(), listCalls, slowCalls, aborted: slowSignal!.aborted }).toEqual({ markers: 1, listCalls: 1, slowCalls: 1, aborted: false });
  await act(async () => { finishSlow(json(200, "처음")); });
  for (let i = 0; i < 3; i++) await flush();
  expect({ listCalls, slowCalls, aborted: slowSignal!.aborted }).toEqual({ listCalls: 2, slowCalls: 2, aborted: false });
  for (let i = 0; i < 3; i++) await flush();
  expect({ listCalls, slowCalls }).toEqual({ listCalls: 2, slowCalls: 2 });   // 한가해진 뒤 한 번만
});

test("편집 중 바뀐 표지는 보류하고 편집이 끝날 때 표지를 다시 묻지 않고 한 번 다시 받는다", async () => {
  serve(url => url === "/api/state/revision" ? json(200, { revision: 2 }) : json(200, { ok: true }));
  let changed!: (d: boolean) => void, ref!: { current: string | null };
  await mount(<><List /><Probe revision={1} dirty="#edit" expose={(f, r) => { changed = f; ref = r; }} /></>);
  await tick();
  await tick();
  expect({ markers: markers(), listCalls }).toEqual({ markers: 2, listCalls: 1 });
  await act(async () => { ref.current = null; changed(false); });
  for (let i = 0; i < 3; i++) await flush();
  expect({ markers: markers(), listCalls }).toEqual({ markers: 2, listCalls: 2 });
});

test("숨긴 탭은 표지를 묻지 않고 보이게 되면 바로 묻는다", async () => {
  const vis = vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
  serve(url => url === "/api/state/revision" ? json(200, { revision: 1 }) : json(200, { ok: true }));
  await mount(<><List /><Probe revision={1} /></>);
  await tick();
  await tick();
  expect(markers()).toBe(0);
  vis.mockReturnValue("visible");
  await act(async () => { document.dispatchEvent(new Event("visibilitychange")); });
  for (let i = 0; i < 3; i++) await flush();
  expect({ markers: markers(), listCalls }).toEqual({ markers: 1, listCalls: 1 });   // 같은 revision = 다시 받지 않는다
});

test("표지 401 = 시작 화면으로 보내고 그 뒤로 표지를 묻지 않는다", async () => {
  serve(url => url === "/api/state/revision" ? json(401, {}) : json(200, { ok: true }));
  const out = vi.fn();
  await mount(<><List /><Probe revision={1} onUnauthorized={out} /></>);
  await tick();
  expect({ out: out.mock.calls.length, markers: markers(), listCalls }).toEqual({ out: 1, markers: 1, listCalls: 1 });
  await tick();
  expect({ out: out.mock.calls.length, markers: markers() }).toEqual({ out: 1, markers: 1 });
});

test("동시에 뜬 두 훅은 기준값을 따로 들고 각자 표지를 묻는다", async () => {
  serve(url => url === "/api/state/revision" ? json(200, { revision: 2 }) : json(200, { ok: true }));
  await mount(<List />);
  const a = await mount(<Probe revision={1} />);   // 기준값 1 → 표지 2 = 바뀜
  await mount(<Probe revision={2} />);             // 기준값 2 → 표지 2 = 그대로
  await tick();
  expect({ markers: markers(), listCalls }).toEqual({ markers: 2, listCalls: 2 });   // 다시 받기는 A 한 번뿐
  await act(async () => { a.render(<Probe revision={2} />); });   // A도 새 상태(2)를 받음
  await tick();
  expect({ markers: markers(), listCalls }).toEqual({ markers: 4, listCalls: 2 });
  act(() => a.root.unmount());
  roots = roots.filter(r => r !== a.root);
  await tick();
  expect({ markers: markers(), listCalls }).toEqual({ markers: 5, listCalls: 2 });   // B는 혼자서 계속 묻는다
});

test("숨은 동안 보류된 다시 받기는 그사이 상태 revision이 표지와 같아져도 보이게 될 때 한 번 처리한다", async () => {
  const vis = vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
  let finishMarker!: (r: Response) => void, markerCalls = 0;
  serve(url => {
    if (url !== "/api/state/revision") return json(200, { ok: true });
    markerCalls++;
    return markerCalls === 1 ? new Promise<Response>(r => { finishMarker = r; }) : json(200, { revision: 2 });
  });
  const { render } = await mount(<><List /><Probe revision={1} /></>);
  await tick();   // 보이는 동안 표지를 묻고 응답을 잡아 둔다
  expect({ markers: markers(), listCalls }).toEqual({ markers: 1, listCalls: 1 });
  vis.mockReturnValue("hidden");
  await act(async () => { document.dispatchEvent(new Event("visibilitychange")); });
  await act(async () => { finishMarker(json(200, { revision: 2 })); });   // 숨은 동안 표지 2 도착 = 보류만
  for (let i = 0; i < 3; i++) await flush();
  expect({ markers: markers(), listCalls }).toEqual({ markers: 1, listCalls: 1 });
  await act(async () => { render(<><List /><Probe revision={2} /></>); });   // 숨은 동안 수동 새로 고침이 상태 2를 줬다
  for (let i = 0; i < 3; i++) await flush();
  expect({ markers: markers(), listCalls }).toEqual({ markers: 1, listCalls: 1 });
  vis.mockReturnValue("visible");
  await act(async () => { document.dispatchEvent(new Event("visibilitychange")); });
  for (let i = 0; i < 3; i++) await flush();
  expect({ markers: markers(), listCalls }).toEqual({ markers: 2, listCalls: 2 });   // 다음 표지도 2지만 보류분은 한 번 처리
  await tick();
  expect({ markers: markers(), listCalls }).toEqual({ markers: 3, listCalls: 2 });   // 한 번뿐
});
