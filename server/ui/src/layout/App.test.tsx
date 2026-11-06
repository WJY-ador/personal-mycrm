// 껍데기(옛 app.html 라우터·다리 — 옛 test_ui_build.py 다리 실행 시험·test_web_home.py 정적 절을 실행 시험으로).
// 뼈대 = 실제 server/app.html(서버가 사용자 응답에서 하듯 관리자 구간을 뺀다) · 상태 = 가짜 /api/state.
import { act, useRef, useState } from "react";
import { onlineManager, QueryClientProvider, useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import page from "../../../app.html?raw";
import { boot } from "../main";
import { queryClient } from "../shared/queries";
import { Editable } from "../shared/Editable";
import { EditCtx, useEditStore, type EditSpec } from "../shared/edit";
import { Editor } from "../shared/Editor";
import type { ScreenProps } from "../shared/ctx";
import { calls, click, flush, installFetch, json, serve, text } from "../test/fakeServer";
import { installMedia } from "../test/meFixture";
import { LOADERS, SCREENS } from "./registry";
import { useAutoRefresh } from "./useAppState";

const ST = { user: { display_name: "홍길동", nav: "new", email: "hong@example.com" }, switches: { trash: false }, generated: "2026-11-03T01:05:00Z",
  inbox: { pending: 2 }, tabs: [], journal: [], candidates: [], questions: [], items: [], item_proposals: [], definitions: [] };
let state: unknown = ST, root: Root | null = null;
const $ = (id: string) => document.getElementById(id)!;

function skeleton(admin = false) {
  const html = admin ? page.replace(/<!--user-->[\s\S]*?<!--\/user-->/g, "") : page.replace(/<!--admin-->[\s\S]*?<!--\/admin-->/g, "");
  const doc = new DOMParser().parseFromString(html, "text/html");
  document.body.replaceChildren(...[...doc.body.childNodes].map(n => document.importNode(n, true)));
}
async function start(hash: string, admin = false) {
  history.replaceState(null, "", hash || location.pathname);
  skeleton(admin);
  await Promise.all(Object.values(LOADERS).map(f => f()));
  await act(async () => { root = boot(); });
  for (let i = 0; i < 4; i++) await flush();
}
async function go(hash: string) {
  await act(async () => { location.hash = hash; window.dispatchEvent(new HashChangeEvent("hashchange")); });
  for (let i = 0; i < 3; i++) await flush();
}

beforeEach(() => {
  onlineManager.setOnline(true);
  installFetch(); installMedia(false); queryClient.clear(); state = ST;
  window.scrollTo = vi.fn();
  HTMLDialogElement.prototype.showModal = function (this: HTMLDialogElement) { this.open = true; };
  HTMLDialogElement.prototype.close = function (this: HTMLDialogElement) { this.open = false; this.dispatchEvent(new Event("close")); };
  serve(url => (url === "/api/state" ? (state ? json(200, state) : Promise.reject(new TypeError("offline"))) : json(404, { code: "NOT-FOUND", msg: "" })));
});
afterEach(() => { if (root) act(() => root!.unmount()); root = null; onlineManager.setOnline(true); vi.unstubAllGlobals(); });

test("오프라인에서 기존 상태를 새로 확인했다고 알리지 않고 온라인에서 재시도한다", async () => {
  await start("#_setup/help");
  onlineManager.setOnline(false);
  await click($("reload"));
  expect($("reload-status").textContent).toBe("서버 상태를 불러오지 못했어요.");
  expect(queryClient.getQueryData(["state"])).toEqual(ST);
  onlineManager.setOnline(true);
  await click($("reload"));
  expect($("reload-status").textContent).toBe("서버 상태를 확인했어요.");
});

test("뼈대 = 인라인 스크립트·스타일 0 · 진입 자리 하나", () => {
  expect(page).not.toMatch(/<script(?![^>]*\bsrc=)[^>]*>/);
  expect(page).not.toMatch(/<style\b/);
  expect(page.match(/<main id="view" class="wrap"><p class="hint" id="boot">불러오는 중이에요…<\/p><\/main>/g)?.length).toBe(1);
});

test("수동 새로 고침은 HTTP 500에서 기존 화면을 유지하고 실패를 알리며 재시도한다", async () => {
  await start("#_setup/help");
  expect($("who").textContent).toBe("hong@example.com");
  serve(url => url === "/api/state" ? json(500, { code: "ERROR", msg: "실패" }) : json(404, {}));
  await click($("reload"));
  expect($("bands").textContent).toContain("서버 상태를 불러오지 못했어요");
  expect($("who").textContent).toBe("hong@example.com");
  expect($("view").textContent).toContain("문의 및 개인정보");
  expect(document.getElementById("reload-status")?.textContent).toContain("서버 상태를 불러오지 못했어요");
  serve(url => url === "/api/state" ? json(200, ST) : json(404, {}));
  await click($("reload"));
  expect($("bands").textContent).toBe("");
  expect(document.getElementById("reload-status")?.textContent).toContain("서버 상태를 확인했어요");
});

test("수동 새로 고침 중 중복을 막고 완료를 발표한다", async () => {
  await start("#_setup/help");
  let finish!: (r: Response) => void;
  serve(url => url === "/api/state" ? new Promise<Response>(r => { finish = r; }) : json(404, {}));
  calls.length = 0;
  await click($("reload"));
  expect(($("reload") as HTMLButtonElement).disabled).toBe(true);
  expect($("reload-status").textContent).toBe("서버 상태를 확인하고 있어요…");
  await click($("reload"));
  expect(calls.filter(c => c.url === "/api/state")).toHaveLength(1);
  await act(async () => { finish(json(200, ST)); });
  await flush();
  expect(($("reload") as HTMLButtonElement).disabled).toBe(false);
  expect($("reload-status").textContent).toBe("서버 상태를 확인했어요.");
});

test("첫 상태 요청 중 새로 고침은 진행 중 요청이 끝날 때까지 기다린다", async () => {
  const pending: ((response: Response) => void)[] = [];
  serve(url => url === "/api/state" ? new Promise<Response>(resolve => pending.push(resolve)) : json(404, {}));
  await start("#_setup/help");
  expect(pending).toHaveLength(1);
  await click($("reload"));
  expect(($("reload") as HTMLButtonElement).disabled).toBe(true);
  expect($("reload-status").textContent).toBe("서버 상태를 확인하고 있어요…");
  await act(async () => pending[0](json(200, ST)));
  await flush();
  expect($("reload-status").textContent).toBe("서버 상태를 확인했어요.");
  expect(($("reload") as HTMLButtonElement).disabled).toBe(false);
});

test("다른 화면 조회가 끝나지 않아도 상태 새로 고침을 완료하고 재시도할 수 있다", async () => {
  const real = SCREENS.help;
  SCREENS.help = () => {
    useQuery({ queryKey: ["stuck-screen"], queryFn: () => new Promise(() => {}) });
    return <p>도움</p>;
  };
  try {
    await start("#_setup/help");
    serve(url => url === "/api/state" ? json(200, ST) : new Promise<Response>(() => {}));
    calls.length = 0;
    await click($("reload"));
    expect(($("reload") as HTMLButtonElement).disabled).toBe(false);
    expect($("reload-status").textContent).toBe("서버 상태를 확인했어요.");
    expect(calls.filter(c => c.url === "/api/state")).toHaveLength(1);
  } finally { SCREENS.help = real; }
});

test("상태 요청 제한 시간이 지나면 요청을 취소하고 수동 재시도를 연다", async () => {
  await start("#_setup/help");
  const timeouts: AbortController[] = [];
  const finish: ((response: Response) => void)[] = [];
  const signals: AbortSignal[] = [];
  vi.spyOn(AbortSignal, "timeout").mockImplementation(() => {
    const timeout = new AbortController();
    timeouts.push(timeout);
    return timeout.signal;
  });
  vi.stubGlobal("fetch", vi.fn((url: string, init?: RequestInit) => {
    calls.push({ url, method: init?.method || "GET" });
    expect(init?.signal?.aborted).toBe(false);
    signals.push(init!.signal!);
    return new Promise<Response>(resolve => { finish.push(resolve); });
  }));
  await click($("reload"));
  expect(($("reload") as HTMLButtonElement).disabled).toBe(true);
  await act(async () => timeouts[0].abort());
  await flush();
  expect(signals[0].aborted).toBe(true);
  expect(($("reload") as HTMLButtonElement).disabled).toBe(false);
  expect($("reload-status").textContent).toBe("서버 상태를 불러오지 못했어요.");
  await click($("reload"));
  expect(finish).toHaveLength(2);
  await act(async () => finish[1](json(200, ST)));
  await flush();
  expect($("reload-status").textContent).toBe("서버 상태를 확인했어요.");
  await act(async () => finish[0](json(200, { ...ST, user: { ...ST.user, email: "late@example.com" } })));
  await flush();
  expect($("who").textContent).toBe("hong@example.com");
  vi.restoreAllMocks();
});

test("수동 새로 고침 실패 중 미저장 입력과 마지막 성공 시각을 보존한다", async () => {
  const real = SCREENS.help;
  SCREENS.help = () => <textarea aria-label="초안" defaultValue="아직 저장하지 않은 내용" />;
  try {
    await start("#_setup/help");
    const draft = document.querySelector<HTMLTextAreaElement>('[aria-label="초안"]')!;
    draft.value = "사용자가 고친 내용";
    serve(url => url === "/api/state" ? json(500, {}) : json(404, {}));
    await click($("reload"));
    expect(document.querySelector<HTMLTextAreaElement>('[aria-label="초안"]')?.value).toBe("사용자가 고친 내용");
    expect($("bands").textContent).toContain("11월 3일 10:05에 불러온 내용이에요.");
  } finally { SCREENS.help = real; }
});

test("최초 상태 요청이 HTTP 500이면 오류 응답을 대시보드 상태로 사용하지 않는다", async () => {
  serve(url => url === "/api/state" ? json(500, { code: "ERROR" }) : json(404, {}));
  await start("#_setup/help");
  expect($("bands").textContent).toContain("서버 상태를 불러오지 못했어요.");
  expect($("nav-tabs").textContent).toBe("");
  expect(queryClient.getQueryState(["state"])?.status).toBe("error");
});

test("쓰기 후 내부 상태 갱신은 수동 새로 고침 문구를 표시하지 않는다", async () => {
  let done: ((text: string) => Promise<unknown>) | undefined;
  const real = SCREENS.help;
  SCREENS.help = ({ ctx }: ScreenProps) => { done = ctx.done; return <p>도움</p>; };
  try {
    await start("#_setup/help");
    await act(async () => { await done!("저장했어요."); });
    expect($("reload-status").textContent).toBe("");
  } finally { SCREENS.help = real; }
});

test("새로 고침 중 화면을 종료해도 늦은 응답이 제거된 UI를 건드리지 않는다", async () => {
  await start("#_setup/help");
  let finish!: (r: Response) => void;
  serve(url => url === "/api/state" ? new Promise<Response>(r => { finish = r; }) : json(404, {}));
  await click($("reload"));
  expect(($("reload") as HTMLButtonElement).disabled).toBe(true);
  await act(async () => root!.unmount());
  root = null;
  expect(document.getElementById("reload-status")).toBeNull();
  expect(($("reload") as HTMLButtonElement).disabled).toBe(false);
  await act(async () => { finish(json(200, ST)); });
  expect(document.getElementById("reload-status")).toBeNull();
});

test("상태 한 벌 → 탭 줄·머리글·바닥 · 설정 페이지 줄 · 문의 버튼 = 껍데기 대화창", async () => {
  await start("#_setup/help");
  expect(calls.map(c => c.url)).toEqual(["/api/state"]);
  expect(text($("nav-tabs"), "a")).toEqual(["나", "오늘2"]);
  expect($("nav-tabs").querySelector(".on")).toBeNull();
  expect($("who").textContent).toBe("hong@example.com");
  expect($("who").title).toBe("hong@example.com");
  expect($("acct-inbox-n").textContent).toBe(" (2)");
  expect($("foot").textContent).toBe("불러온 시각 11월 3일 10:05.");
  expect($("subnav").hidden).toBe(false);
  expect($("subnav").querySelector("a.on")!.textContent).toBe("문의 및 개인정보");
  expect(text($("subnav"), "a")).toEqual(["페이지 레이아웃", "내 구조 설정", "자료 종류", "연결 장치", "지도", "문의 및 개인정보", "이관"]);   // 휴지통 = 스위치 켜짐만 · 운영 링크 = 관리자만
  expect(($("setup-link") as HTMLAnchorElement).getAttribute("href")).toBe("#_setup");
  expect(document.body.classList.contains("navnew-screen")).toBe(true);
  expect($("view").textContent).toContain("문의 및 개인정보");
  await click($("view").querySelector('[data-open="mine"]'));
  expect(($("desk-dlg") as HTMLDialogElement).open).toBe(true);
  expect($("desk-dlg-title").textContent).toBe("내 문의");
});

test("관리자 — Setup 줄 끝에 운영 관리·운영 콘솔 · 문의 자리 없음", async () => {
  state = { ...ST, user: { ...ST.user, admin: true } };
  await start("#_setup", true);
  const links = [...$("subnav").querySelectorAll("a")].map(a => [a.textContent, a.getAttribute("href")]);
  expect(links.slice(-2)).toEqual([["운영 관리", "/admin/setup"], ["운영 콘솔", "/admin"]]);
  expect(document.getElementById("ui-desk")).toBeNull();
  expect($("acct-menu").querySelector('[data-acct="send"]')).toBeNull();
});

test("옛 주소 = replace · 판단 검토의 돌아갈 곳 = 그 탭에서 마지막으로 본 주소", async () => {
  await start("#_obj");
  expect(location.hash).toBe("#_setup/objects");
  expect($("subnav").querySelector("a.on")!.textContent).toBe("자료 종류");
  await go("#_settings");
  expect(location.hash).toBe("#_setup/structure");
  await go("#journal");
  expect($("nav-tabs").querySelector(".on")).toBeNull();
  const seen: string[][] = [];
  const real = SCREENS.review;
  SCREENS.review = ({ ctx }: ScreenProps) => { seen.push(ctx.args || []); return <p>대조</p>; };
  try {
    await go("#journal/review/r:r1/c1");
    expect(seen.at(-1)).toEqual(["journal", "r:r1", "c1", "#journal", "기록으로 돌아가기"]);
    expect($("subnav").hidden).toBe(true);
  } finally { SCREENS.review = real; }
});

test("이름 관문 — 표시 이름이 비면 탭·마스트·대화 서랍 없이 관문 · 바닥 안내 · 관리자 톱니 = 운영 경로", async () => {
  state = { ...ST, user: { ...ST.user, display_name: "", admin: true } };
  await start("#_me", true);
  expect($("view").textContent).toContain("표시 이름을 정해 주세요");
  expect($("nav-tabs").textContent).toBe("");
  expect($("ui-mast").textContent).toBe("");
  expect($("foot").textContent).toBe("표시 이름을 정하면 대시보드가 열려요.");
  expect($("acct-name").hidden).toBe(true);
  expect(($("setup-link") as HTMLAnchorElement).getAttribute("href")).toBe("/admin/setup");
  expect(document.getElementById("ui-desk")).toBeNull();   // 관리자 응답 = 문의 자리 없음
  expect($("view").querySelector('[data-open="send"]')).toBeNull();   // 관리자 = 문의 버튼 없음(열 자리도 없다)
  expect(document.getElementById("desk-dlg")).toBeNull();
});

test("계정 메뉴 — 표시 이름 바꾸기 = 대화창(지금 이름) · 저장 승인 대기 = #_inbox → 오늘 · 메뉴 밖 = 닫기", async () => {
  await start("#_me");
  const acct = $("acct") as HTMLDetailsElement;
  acct.open = true;
  await click($("acct-name"));
  expect(acct.open).toBe(false);
  expect(($("name-dlg") as HTMLDialogElement).open).toBe(true);
  expect(($("name-dlg").querySelector("input") as HTMLInputElement).value).toBe("홍길동");
  acct.open = true;
  await click($("acct-inbox"));
  for (let i = 0; i < 3; i++) await flush();
  expect(location.hash).toBe("#_today");
  expect($("nav-tabs").querySelector(".on")!.textContent).toBe("오늘2");
  acct.open = true;
  await click($("foot"));
  expect(acct.open).toBe(false);
});

test("미저장 보호 — 고치던 주소를 떠나면 되돌리고 묻는다 · 계속 편집 = 그대로 · 변경 버리기 = 가려던 주소", async () => {
  const real = SCREENS.help;
  SCREENS.help = ({ ctx }: ScreenProps) => { ctx.setDirty?.("#_setup/help"); return <p>고치는 중</p>; };
  try {
    await start("#_setup/help");
    await go("#_me");
    expect(location.hash).toBe("#_setup/help");
    expect(($("leave-dlg") as HTMLDialogElement).open).toBe(true);
    expect($("view").querySelector("p")!.textContent).toBe("고치는 중");
    await click($("leave-stay"));
    expect(($("leave-dlg") as HTMLDialogElement).open).toBe(false);
    await go("#_today");
    await click($("leave-go"));
    for (let i = 0; i < 3; i++) await flush();
    expect(location.hash).toBe("#_today");
  } finally { SCREENS.help = real; }
});

test("주기 갱신 — 열린 화면의 활성 상태와 목록을 30초마다 다시 받고 무한 목록의 cursor를 유지한다", async () => {
  const real = SCREENS.help;
  let stateVersion = 1, pageCalls: string[] = [];
  serve(url => {
    if (url === "/api/state") return json(200, { ...ST, revision: stateVersion, user: { ...ST.user, display_name: `이름${stateVersion}` } });
    if (url === "/api/state/revision") return json(200, { revision: stateVersion });
    if (url.startsWith("/api/page")) {
      const cursor = new URL(url, "http://local").searchParams.get("cursor") || "first";
      pageCalls.push(cursor);
      return json(200, cursor === "first" ? { items: ["첫째"], next: "c1" } : { items: ["둘째"], next: null });
    }
    return json(404, {});
  });
  SCREENS.help = () => {
    const list = useInfiniteQuery({
      queryKey: ["auto-pages"],
      queryFn: async ({ pageParam }) => (await fetch(`/api/page?cursor=${pageParam || "first"}`)).json() as Promise<{ items: string[]; next: string | null }>,
      initialPageParam: null as string | null,
      getNextPageParam: page => page.next,
    });
    return <button id="next-page" onClick={() => void list.fetchNextPage()}>다음</button>;
  };
  vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
  try {
    await start("#_setup/help");
    await click($("next-page"));
    expect(queryClient.getQueryData<{ pages: unknown[]; pageParams: unknown[] }>(["auto-pages"])?.pageParams).toEqual([null, "c1"]);
    stateVersion = 2;
    pageCalls = [];
    await act(async () => { await vi.advanceTimersByTimeAsync(30_000); });
    await flush();
    expect($("who").textContent).toBe("hong@example.com"); // header email is unchanged
    expect(queryClient.getQueryState(["state"])?.data).toMatchObject({ user: { display_name: "이름2" } });
    expect(pageCalls).toEqual(["first", "c1"]);
    expect(queryClient.getQueryData<{ pages: unknown[]; pageParams: unknown[] }>(["auto-pages"])?.pageParams).toEqual([null, "c1"]);
  } finally { vi.useRealTimers(); SCREENS.help = real; }
});

test("주기 갱신 — 편집 중인 자동 재조회는 보류하고 편집 종료 때 최신 데이터를 반영하며 초안을 보존한다", async () => {
  const real = SCREENS.help;
  let version = 1;
  serve(url => url === "/api/state"
    ? json(200, { ...ST, revision: version, user: { ...ST.user, display_name: `이름${version}` } })
    : url === "/api/state/revision" ? json(200, { revision: version })
    : url === "/api/list" ? json(200, { version }) : json(404, {}));
  SCREENS.help = ({ ctx }: ScreenProps) => {
    const [draft, setDraft] = useState("기존 초안");
    const q = useQuery({ queryKey: ["auto-list"], queryFn: async () => { const r = await fetch("/api/list"); if (!r.ok) throw new Error("list failed"); return r.json() as Promise<{ version: number }>; } });
    return <>
      <p id="auto-version">{q.data?.version}</p><p id="auto-draft">{draft}</p>
      <button id="start-auto-edit" onClick={() => { setDraft("미저장 편집"); ctx.setDirty?.("#_setup/help"); }}>편집</button>
      <button id="finish-auto-edit" onClick={() => ctx.setDirty?.(null)}>편집 종료</button>
    </>;
  };
  vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
  try {
    await start("#_setup/help");
    await click($("start-auto-edit"));
    version = 2;
    calls.length = 0;
    await act(async () => { await vi.advanceTimersByTimeAsync(30_000); });
    await flush();
    expect(calls).toEqual([{ url: "/api/state/revision", method: "GET" }]);   // 표지만 묻고 다시 받기는 보류
    calls.length = 0;
    expect($("auto-version").textContent).toBe("1");
    expect($("auto-draft").textContent).toBe("미저장 편집");
    await click($("finish-auto-edit"));
    await flush();
    expect(calls.map(c => c.url).sort()).toEqual(["/api/list", "/api/state"]);
    expect(queryClient.getQueryData(["state"])).toMatchObject({ user: { display_name: "이름2" } });
    expect({ text: $("auto-version").textContent, data: queryClient.getQueryData(["auto-list"]), calls }).toEqual({ text: "2", data: { version: 2 }, calls });
    expect($("auto-draft").textContent).toBe("미저장 편집");
  } finally { vi.useRealTimers(); SCREENS.help = real; }
});

test("편집 시작은 이미 진행 중인 장치·상세·더 보기 사용자 조회를 취소하지 않는다", async () => {
  const real = SCREENS.help;
  const finish: Record<string, (r: Response) => void> = {};
  let deviceSignal: AbortSignal | undefined, detailSignal: AbortSignal | undefined, nextSignal: AbortSignal | undefined;
  serve(url => {
    if (url === "/api/state") return json(200, ST);
    if (url === "/api/pages?cursor=first") return json(200, { rows: ["첫 페이지"], next: "next" });
    return new Promise<Response>(resolve => { finish[url] = resolve; });
  });
  SCREENS.help = ({ ctx }: ScreenProps) => {
    const [draft, setDraft] = useState("초안");
    const device = useQuery({ queryKey: ["device"], enabled: false, queryFn: ({ signal }) => { deviceSignal = signal; return fetch("/api/device", { signal }).then(r => r.json() as Promise<string>); } });
    const detail = useQuery({ queryKey: ["detail"], enabled: false, queryFn: ({ signal }) => { detailSignal = signal; return fetch("/api/detail", { signal }).then(r => r.json() as Promise<string>); } });
    const pages = useInfiniteQuery({
      queryKey: ["user-pages"], initialPageParam: "first",
      queryFn: ({ pageParam, signal }) => {
        if (pageParam === "next") nextSignal = signal;
        return fetch(`/api/pages?cursor=${pageParam}`, { signal }).then(r => r.json() as Promise<{ rows: string[]; next: string | null }>);
      }, getNextPageParam: page => page.next || undefined,
    });
    return <>
      <p id="user-draft">{draft}</p>
      <p id="user-results">{[device.data, detail.data, ...pages.data?.pages.flatMap(p => p.rows) || []].join("|")}</p>
      <button id="user-requests" onClick={() => { void device.refetch(); void detail.refetch(); void pages.fetchNextPage(); }}>요청</button>
      <button id="user-edit" onClick={() => { setDraft("편집 초안"); ctx.setDirty?.("#_setup/help"); }}>편집</button>
    </>;
  };
  try {
    await start("#_setup/help");
    await click($("user-requests"));
    await flush();
    expect(deviceSignal).toBeDefined();
    expect(detailSignal).toBeDefined();
    expect(nextSignal).toBeDefined();
    await click($("user-edit"));
    expect(deviceSignal!.aborted).toBe(false);
    expect(detailSignal!.aborted).toBe(false);
    expect(nextSignal!.aborted).toBe(false);
    await act(async () => {
      finish["/api/device"](json(200, "장치 완료"));
      finish["/api/detail"](json(200, "상세 완료"));
      finish["/api/pages?cursor=next"](json(200, { rows: ["두 번째 페이지"], next: null }));
    });
    await flush();
    expect($("user-draft").textContent).toBe("편집 초안");
    expect($("user-results").textContent).toContain("장치 완료|상세 완료|첫 페이지|두 번째 페이지");
  } finally { SCREENS.help = real; }
});

test("느린 자동 상태 poll이 편집 입력 뒤 완료돼도 실제 Editor 초안과 이탈 잠금이 유지된다", async () => {
  const real = SCREENS.help;
  let stateCalls = 0, finishPoll!: (r: Response) => void;
  serve(url => {
    if (url === "/api/state/revision") return json(200, { revision: 2 });
    if (url !== "/api/state") return json(404, {});
    if (++stateCalls === 1) return json(200, { ...ST, revision: 1 });
    return new Promise<Response>(resolve => { finishPoll = resolve; });
  });
  SCREENS.help = ({ ctx }: ScreenProps) => {
    const edit = useEditStore(ctx);
    const spec: EditSpec = {
      key: "display-name", done: "저장했어요.", errText: () => "저장 실패",
      fields: [{ name: "name", label: "표시 이름", multi: false, orig: ctx.state?.user.display_name || "" }],
      save: async () => {},
    };
    return <EditCtx.Provider value={edit}>{edit.edit ? <Editor /> : <Editable spec={spec}>{ctx.state?.user.display_name}</Editable>}</EditCtx.Provider>;
  };
  vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
  try {
    await start("#_setup/help");
    await act(async () => { await vi.advanceTimersByTimeAsync(30_000); });
    expect(stateCalls).toBe(2);
    await click($("view").querySelector("button")!);
    const input = $("hedit-input") as HTMLInputElement;
    const setValue = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
    await act(async () => { setValue.call(input, "미저장 이름"); input.dispatchEvent(new Event("input", { bubbles: true })); });
    await flush();
    expect(input.value).toBe("미저장 이름");
    expect(($("hedit-input") as HTMLInputElement).disabled).toBe(false);
    await act(async () => { finishPoll(json(200, { ...ST, revision: 2, user: { ...ST.user, display_name: "서버에서 바뀐 이름" } })); });
    await flush();
    expect(($("hedit-input") as HTMLInputElement).value).toBe("미저장 이름");
    expect(($("hedit-input") as HTMLInputElement).disabled).toBe(false);
    expect(queryClient.getQueryData(["state"])).toMatchObject({ user: { display_name: "서버에서 바뀐 이름" } });
    await go("#_today");
    expect(location.hash).toBe("#_setup/help");
    expect(($("leave-dlg") as HTMLDialogElement).open).toBe(true);
    expect(($("hedit-input") as HTMLInputElement).value).toBe("미저장 이름");
  } finally { vi.useRealTimers(); SCREENS.help = real; }
});

test("느린 자동 poll이 검토 카드 편집 중 완료돼도 review 초안 등록과 이탈 잠금이 유지된다", async () => {
  let stateCalls = 0, finishPoll!: (r: Response) => void;
  const reviewState = { ...ST,
    questions: [{ id: "q_test", text: "질문 하나", created: "" }],
    journal: [{ id: "r_test", title: "기록 하나", excerpt: "", created: "", source: null, source_id: "s_test", question_id: "q_test", source_date: null, author_kind: "self" }],
    sources: [{ id: "s_test", kind: "file", name: "기록 파일", location: null }],
    candidates: [{ id: "c_test", text: "담당을 먼저 정한다", status: "pending", record_id: "r_test", question_id: "q_test", quote: "입력 담당을 먼저", review: null, revision: 2, created: "", origin: "ai", edited_by_user: false, wording_by: "ai", wording_approved: false }],
  };
  serve(url => {
    if (url === "/api/state/revision") return json(200, { revision: 2 });
    if (url === "/api/state") {
      if (++stateCalls === 1) return json(200, { ...reviewState, revision: 1 });
      return new Promise<Response>(resolve => { finishPoll = resolve; });
    }
    if (url.startsWith("/api/journal?id=r_test")) return json(200, { id: "r_test", title: "기록 하나", body: "첫 문단. 입력 담당을 먼저 정했다. 끝 문단.", revision: 1, author_kind: "self", meta: { created: "", source: "기록 파일", question_id: "q_test" } });
    return json(404, {});
  });
  vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
  try {
    await start("#q/review/q_test/c_test");
    expect($("view").textContent).toContain("원문과 대조하기");
    await act(async () => { await vi.advanceTimersByTimeAsync(30_000); });
    expect(stateCalls).toBe(2);
    await click([...$("view").querySelectorAll("button")].find(b => b.textContent === "고쳐서 남기기")!);
    const edit = $("rvtext") as HTMLTextAreaElement;
    const setValue = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!;
    await act(async () => { setValue.call(edit, "검토 중 미저장 문장"); edit.dispatchEvent(new Event("input", { bubbles: true })); });
    await flush();
    expect(edit.value).toBe("검토 중 미저장 문장");
    expect(($("leave-dlg") as HTMLDialogElement).open).toBe(false);
    await act(async () => { finishPoll(json(200, { ...reviewState, revision: 2, user: { ...ST.user, display_name: "새 표시 이름" } })); });
    await flush();
    expect(queryClient.getQueryData(["state"])).toMatchObject({ user: { display_name: "새 표시 이름" } });
    expect(($("rvtext") as HTMLTextAreaElement).value).toBe("검토 중 미저장 문장");
    expect(($("leave-dlg") as HTMLDialogElement).open).toBe(false);
    await go("#_today");
    expect(location.hash).toBe("#q/review/q_test/c_test");
    expect(($("leave-dlg") as HTMLDialogElement).open).toBe(true);
    expect(($("rvtext") as HTMLTextAreaElement).value).toBe("검토 중 미저장 문장");
  } finally { vi.useRealTimers(); }
});

test("주기 갱신 — 숨긴 탭은 정지하고 보이면 즉시 확인하며 실패 때 이전 화면을 보존한다", async () => {
  const real = SCREENS.help;
  let version = 1, fail = false;
  serve(url => {
    if (url === "/api/state/revision") return json(200, { revision: version });   // 표지는 성공 — 다시 받기만 실패시킨다
    if (fail) return json(503, {});
    if (url === "/api/state") return json(200, { ...ST, revision: version, user: { ...ST.user, display_name: `이름${version}` } });
    if (url === "/api/list") return json(200, { version });
    return json(404, {});
  });
  SCREENS.help = () => {
    const q = useQuery({ queryKey: ["auto-list"], queryFn: async () => { const r = await fetch("/api/list"); if (!r.ok) throw new Error("list failed"); return r.json() as Promise<{ version: number }>; } });
    return <p id="auto-version">{q.data?.version}</p>;
  };
  const visibility = vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
  try {
    await start("#_setup/help");
    version = 2;
    calls.length = 0;
    await act(async () => { await vi.advanceTimersByTimeAsync(30_000); });
    expect(calls).toEqual([]);
    visibility.mockReturnValue("visible");
    document.dispatchEvent(new Event("visibilitychange"));
    await flush();
    await flush();
    expect(calls.map(c => c.url).sort()).toEqual(["/api/list", "/api/state", "/api/state/revision"]);
    expect($("auto-version").textContent).toBe("2");
    fail = true;
    version = 3;
    calls.length = 0;
    await act(async () => { await vi.advanceTimersByTimeAsync(30_000); });
    await flush();
    expect(calls.map(c => c.url).sort()).toEqual(["/api/list", "/api/state", "/api/state/revision"]);
    expect({ text: $("auto-version").textContent, list: queryClient.getQueryData(["auto-list"]), state: queryClient.getQueryData(["state"]) }).toMatchObject({ text: "2", list: { version: 2 }, state: { user: { display_name: "이름2" } } });
    fail = false;   // 실패한 다시 받기는 보류로 남아 다음 tick에 재시도한다
    calls.length = 0;
    await act(async () => { await vi.advanceTimersByTimeAsync(30_000); });
    await flush();
    await flush();
    expect(calls.map(c => c.url).sort()).toEqual(["/api/list", "/api/state", "/api/state/revision"]);
    expect({ text: $("auto-version").textContent, state: queryClient.getQueryData(["state"]) }).toMatchObject({ text: "3", state: { revision: 3, user: { display_name: "이름3" } } });
  } finally { vi.useRealTimers(); SCREENS.help = real; }
});

// revision 기반 자동 갱신 계약(합성 응답) — /api/state 응답의 revision = 기준값, GET /api/state/revision = { revision } 표지.
// 30초 tick 마다 표지만 묻고, 표지가 기준값과 다를 때만 상태와 지금 떠 있는 목록을 다시 받는다.
function revisionServer(r: { state: () => number; marker: () => number; list: () => number }) {
  serve(url => {
    if (url === "/api/state") return json(200, { ...ST, revision: r.state() });
    if (url === "/api/state/revision") return json(200, { revision: r.marker() });
    if (url === "/api/list") return json(200, { version: r.list() });
    return json(404, {});
  });
}
function revisionListScreen() {
  const q = useQuery({ queryKey: ["auto-list"], queryFn: async () => { const r = await fetch("/api/list"); if (!r.ok) throw new Error("list failed"); return r.json() as Promise<{ version: number }>; } });
  return <p id="auto-version">{q.data?.version}</p>;
}
async function tick30s() {
  await act(async () => { await vi.advanceTimersByTimeAsync(30_000); });
  for (let i = 0; i < 3; i++) await flush();
}
const urls = () => calls.map(c => c.url);

test("revision 갱신 — 표지가 기준값 1 그대로면 30초 뒤 GET /api/state/revision 만 부르고 상태와 목록은 다시 받지 않는다", async () => {
  const real = SCREENS.help;
  revisionServer({ state: () => 1, marker: () => 1, list: () => 1 });
  SCREENS.help = revisionListScreen;
  vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
  try {
    await start("#_setup/help");
    expect(queryClient.getQueryData(["state"])).toMatchObject({ revision: 1 });
    expect($("auto-version").textContent).toBe("1");
    calls.length = 0;
    await tick30s();
    expect(calls).toEqual([{ url: "/api/state/revision", method: "GET" }]);
    expect(queryClient.getQueryData(["state"])).toMatchObject({ revision: 1 });
    expect($("auto-version").textContent).toBe("1");
  } finally { vi.useRealTimers(); SCREENS.help = real; }
});

test("revision 갱신 — 표지가 2로 바뀌면 표지 확인 뒤 활성 상태와 목록을 다시 받고 기준값을 2로 옮긴다", async () => {
  const real = SCREENS.help;
  let rev = 1;
  revisionServer({ state: () => rev, marker: () => rev, list: () => rev });
  SCREENS.help = revisionListScreen;
  vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
  try {
    await start("#_setup/help");
    expect(queryClient.getQueryData(["state"])).toMatchObject({ revision: 1 });
    rev = 2;
    calls.length = 0;
    await tick30s();
    expect(urls()[0]).toBe("/api/state/revision");
    expect(urls().slice(1).sort()).toEqual(["/api/list", "/api/state"]);
    expect(queryClient.getQueryData(["state"])).toMatchObject({ revision: 2 });
    expect($("auto-version").textContent).toBe("2");
    calls.length = 0;
    await tick30s();
    expect(urls()).toEqual(["/api/state/revision"]);   // 새 기준값 2 = 표지 2 → 다시 받지 않는다
  } finally { vi.useRealTimers(); SCREENS.help = real; }
});

test("revision 갱신 — 상태 로딩 중 바뀐 변경을 놓치지 않는다: 상태 기준값 4 · 첫 표지 5 = 다시 받기", async () => {
  const real = SCREENS.help;
  let stateCalls = 0, listCalls = 0;
  // 서버는 이미 5 — 첫 /api/state 는 로딩 도중 바뀌기 전 스냅숏(4)을 돌려준다. 표지를 기준값으로 삼으면 이 변경을 놓친다
  revisionServer({ state: () => (++stateCalls === 1 ? 4 : 5), marker: () => 5, list: () => ++listCalls });
  SCREENS.help = revisionListScreen;
  vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
  try {
    await start("#_setup/help");   // calls 를 비우지 않는다 — 시작 직후 표지 확인을 하는 구현도 같은 계약으로 본다
    await tick30s();
    const firstMarker = urls().indexOf("/api/state/revision");
    expect(firstMarker).toBeGreaterThanOrEqual(0);
    expect(urls().filter(u => u === "/api/state")).toHaveLength(2);
    expect(urls().filter(u => u === "/api/list")).toHaveLength(2);
    expect(urls().lastIndexOf("/api/state")).toBeGreaterThan(firstMarker);   // 두 번째 상태 조회 = 표지 5 를 본 뒤
    expect(queryClient.getQueryData(["state"])).toMatchObject({ revision: 5 });
    expect($("auto-version").textContent).toBe("2");
    calls.length = 0;
    await tick30s();
    expect(urls()).toEqual(["/api/state/revision"]);   // 기준값 5 = 표지 5 → 더 받지 않는다
  } finally { vi.useRealTimers(); SCREENS.help = real; }
});

test("결과 한 줄(done) = 상태를 다시 받고 그 주소 화면에 한 번 · 못 받음 = 띠(앞 화면 그대로) · reload = 받았는지", async () => {
  const flashes: unknown[] = [];
  let done: ((t: string, h?: string) => Promise<unknown>) | undefined, rel: (() => Promise<unknown>) | undefined;
  const real = SCREENS.help;
  SCREENS.help = ({ ctx }: ScreenProps) => { flashes.push(ctx.flash || null); done = ctx.done; rel = ctx.reload; return <p>도움</p>; };
  try {
    await start("#_setup/help");
    calls.length = 0;
    await act(async () => { await done!("저장했어요."); });
    await flush();
    expect(calls.map(c => c.url)).toEqual(["/api/state"]);
    expect(flashes.filter(Boolean)).toEqual([{ text: "저장했어요.", at: "#_setup/help" }]);
    state = null;
    let ok: unknown;
    await act(async () => { ok = await rel!(); });
    await flush();
    expect(ok).toBe(false);
    expect($("bands").textContent).toContain("서버 상태를 불러오지 못했어요.");
    expect($("bands").textContent).toContain("11월 3일 10:05에 불러온 내용이에요.");
    expect($("view").querySelector("p")!.textContent).toBe("도움");
    state = ST;
    await act(async () => { ok = await rel!(); });
    await flush();
    expect(ok).toBe(true);
    expect($("bands").textContent).toBe("");
  } finally { SCREENS.help = real; }
});

test("못 읽음 — 데이터 폴더 = 화면 대신 안내 · 탭 설정 = 띠", async () => {
  state = { ...ST, read: { meta: { ok: false, error: { code: "OFFLINE", msg: "x" } } } };
  await start("#_me");
  expect($("view").textContent).toContain("이 데이터 폴더을 읽지 못했어요");
  state = { ...ST, read: { tabs: { ok: false, error: { code: "UNAUTHORIZED", msg: "" } } } };
  queryClient.clear();
  await act(async () => { root!.unmount(); });
  await start("#_setup/help");
  expect($("bands").textContent).toContain("탭 설정을 읽지 못해 기본 화면을 보여 드려요.");
  expect($("bands").textContent).toContain("로그인이 풀렸어요.");
});

// revision 갱신 빈틈 — 표지 401 · 숨은 탭 · 진행 중 조회 · 표지 실패 재시도 · 훅 둘.
const count = (u: string) => urls().filter(x => x === u).length;
function RevisionProbe({ revision, onUnauthorized }: { revision: number | null; onUnauthorized?: () => void }) {
  const dirty = useRef<string | null>(null);
  useAutoRefresh(true, dirty, revision, { onUnauthorized });
  return null;
}
function RevisionData() {
  useQuery({ queryKey: ["probe-state"], queryFn: async () => (await fetch("/api/state")).json() as Promise<unknown> });
  useQuery({ queryKey: ["probe-list"], queryFn: async () => (await fetch("/api/list")).json() as Promise<unknown> });
  return null;
}
async function mountProbe(node: React.ReactNode, roots: Root[]) {
  const el = document.createElement("div");
  document.body.append(el);
  const r = createRoot(el);
  roots.push(r);
  await act(async () => { r.render(<QueryClientProvider client={queryClient}>{node}</QueryClientProvider>); });
  await flush();
}

test("revision 갱신 — 표지 401 = onUnauthorized 한 번, 주소 이동 없음, 상태와 목록을 다시 받지 않는다", async () => {
  const roots: Root[] = [];
  const onUnauthorized = vi.fn();
  serve(url => url === "/api/state/revision" ? json(401, { code: "UNAUTHORIZED", msg: "" }) : json(200, { revision: 1 }));
  const vis = vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
  const href = location.href;
  try {
    await mountProbe(<><RevisionData /><RevisionProbe revision={1} onUnauthorized={onUnauthorized} /></>, roots);
    calls.length = 0;
    await tick30s();
    expect(urls()).toEqual(["/api/state/revision"]);
    expect(onUnauthorized).toHaveBeenCalledTimes(1);
    expect(location.href).toBe(href);
    await tick30s();
    await tick30s();
    expect(onUnauthorized).toHaveBeenCalledTimes(1);
    expect(count("/api/state") + count("/api/list")).toBe(0);
  } finally { for (const r of roots) act(() => r.unmount()); vi.useRealTimers(); vis.mockRestore(); }
});

test("revision 갱신 — 표지 응답(2)이 탭이 숨은 뒤 도착하면 다시 받지 않고, 다시 보일 때 한 번 다시 받는다", async () => {
  const real = SCREENS.help;
  let rev = 1, hold = false, release!: () => void;
  serve(url => {
    if (url === "/api/state") return json(200, { ...ST, revision: rev });
    if (url === "/api/list") return json(200, { version: rev });
    if (url === "/api/state/revision") {
      if (!hold) return json(200, { revision: rev });
      return new Promise<Response>(r => { release = () => r(json(200, { revision: rev })); });
    }
    return json(404, {});
  });
  SCREENS.help = revisionListScreen;
  let visible: DocumentVisibilityState = "visible";
  const vis = vi.spyOn(document, "visibilityState", "get").mockImplementation(() => visible);
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
  try {
    await start("#_setup/help");
    calls.length = 0;
    hold = true; rev = 2;
    await tick30s();
    expect(urls()).toEqual(["/api/state/revision"]);   // 표지 요청이 떠 있다
    visible = "hidden";
    await act(async () => { document.dispatchEvent(new Event("visibilitychange")); });
    hold = false;
    await act(async () => { release(); });
    for (let i = 0; i < 3; i++) await flush();
    expect({ state: count("/api/state"), list: count("/api/list") }).toEqual({ state: 0, list: 0 });   // 숨은 탭 = 다시 받지 않는다
    expect($("auto-version").textContent).toBe("1");
    await tick30s();
    expect({ state: count("/api/state"), list: count("/api/list") }).toEqual({ state: 0, list: 0 });
    visible = "visible";
    await act(async () => { document.dispatchEvent(new Event("visibilitychange")); });
    for (let i = 0; i < 3; i++) await flush();
    expect({ state: count("/api/state"), list: count("/api/list") }).toEqual({ state: 1, list: 1 });
    expect(queryClient.getQueryData(["state"])).toMatchObject({ revision: 2 });
    expect($("auto-version").textContent).toBe("2");
  } finally { vi.useRealTimers(); vis.mockRestore(); SCREENS.help = real; }
});

test("revision 갱신 — 다른 사용자 조회가 진행 중이면 표지 2를 보류하고, 끝난 뒤 정확히 한 번 다시 받는다", async () => {
  const real = SCREENS.help;
  let rev = 1, slowCalls = 0, finishSlow!: () => void;
  serve(url => {
    if (url === "/api/state") return json(200, { ...ST, revision: rev });
    if (url === "/api/list") return json(200, { version: rev });
    if (url === "/api/state/revision") return json(200, { revision: rev });
    if (url === "/api/slow") {
      if (++slowCalls === 2) return new Promise<Response>(r => { finishSlow = () => r(json(200, { slow: slowCalls })); });
      return json(200, { slow: slowCalls });
    }
    return json(404, {});
  });
  const fetchSlow = async () => (await fetch("/api/slow")).json() as Promise<{ slow: number }>;
  SCREENS.help = () => {
    const slow = useQuery({ queryKey: ["user-slow"], queryFn: fetchSlow });
    return <>{revisionListScreen()}<p id="slow">{slow.data?.slow}</p></>;
  };
  const vis = vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
  try {
    await start("#_setup/help");
    // 사용자 조회 하나만 다시 받기 시작(진행 중으로 남는다) — 자동 갱신과 무관한 조회
    await act(async () => { void queryClient.refetchQueries({ queryKey: ["user-slow"] }); });
    await flush();
    expect(queryClient.isFetching({ queryKey: ["user-slow"] })).toBe(1);
    calls.length = 0;
    rev = 2;
    await tick30s();
    expect(urls()).toEqual(["/api/state/revision"]);   // 바뀐 표지 · 진행 중 조회 = 보류
    await tick30s();
    expect(count("/api/state") + count("/api/list")).toBe(0);
    expect($("auto-version").textContent).toBe("1");
    await act(async () => { finishSlow(); });
    for (let i = 0; i < 4; i++) await flush();
    expect({ state: count("/api/state"), list: count("/api/list") }).toEqual({ state: 1, list: 1 });
    expect(queryClient.getQueryData(["state"])).toMatchObject({ revision: 2 });
    expect($("auto-version").textContent).toBe("2");
    calls.length = 0;
    await tick30s();
    expect(urls()).toEqual(["/api/state/revision"]);   // 기준값 2 = 표지 2
  } finally { vi.useRealTimers(); vis.mockRestore(); SCREENS.help = real; }
});

test("revision 갱신 — 표지 연결 실패·503은 다음 tick에 다시 묻고, 그 사이 바뀐 revision을 잡는다", async () => {
  const real = SCREENS.help;
  let rev = 1, markerCalls = 0;
  const replies: Array<() => Response | Promise<Response>> = [
    () => Promise.reject(new TypeError("offline")),
    () => json(503, { code: "UNAVAILABLE", msg: "" }),
  ];
  serve(url => {
    if (url === "/api/state") return json(200, { ...ST, revision: rev });
    if (url === "/api/list") return json(200, { version: rev });
    if (url === "/api/state/revision") { const f = replies[markerCalls++]; return f ? f() : json(200, { revision: rev }); }
    return json(404, {});
  });
  SCREENS.help = revisionListScreen;
  const vis = vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
  try {
    await start("#_setup/help");
    calls.length = 0;
    await tick30s();   // 연결 실패
    rev = 2;           // 실패 사이에 서버가 바뀐다
    await tick30s();   // 503
    expect(urls()).toEqual(["/api/state/revision", "/api/state/revision"]);
    expect($("auto-version").textContent).toBe("1");
    expect($("bands").textContent).toBe("");   // 표지 실패는 조용히
    await tick30s();   // 표지 2
    expect(urls().slice(0, 3)).toEqual(["/api/state/revision", "/api/state/revision", "/api/state/revision"]);
    expect({ state: count("/api/state"), list: count("/api/list") }).toEqual({ state: 1, list: 1 });
    expect(queryClient.getQueryData(["state"])).toMatchObject({ revision: 2 });
    expect($("auto-version").textContent).toBe("2");
  } finally { vi.useRealTimers(); vis.mockRestore(); SCREENS.help = real; }
});

test("revision 갱신 — 같은 기준값 1의 훅 둘 = 표지가 그대로면 각자 표지만 묻고 상태·목록은 받지 않는다", async () => {
  const roots: Root[] = [];
  serve(url => url === "/api/state/revision" ? json(200, { revision: 1 }) : json(200, { revision: 1 }));
  const vis = vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
  try {
    await mountProbe(<><RevisionData /><RevisionProbe revision={1} /></>, roots);
    await mountProbe(<RevisionProbe revision={1} />, roots);
    calls.length = 0;
    for (let i = 1; i <= 3; i++) {
      await tick30s();
      expect(count("/api/state/revision")).toBe(2 * i);
      expect(urls().every(u => u === "/api/state/revision")).toBe(true);
    }
  } finally { for (const r of roots) act(() => r.unmount()); vi.useRealTimers(); vis.mockRestore(); }
});
