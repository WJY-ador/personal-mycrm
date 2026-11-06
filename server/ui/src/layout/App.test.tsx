// 껍데기(옛 app.html 라우터·다리 — 옛 test_ui_build.py 다리 실행 시험·test_web_home.py 정적 절을 실행 시험으로).
// 뼈대 = 실제 server/app.html(서버가 사용자 응답에서 하듯 관리자 구간을 뺀다) · 상태 = 가짜 /api/state.
import { act } from "react";
import { onlineManager, useQuery } from "@tanstack/react-query";
import type { Root } from "react-dom/client";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import page from "../../../app.html?raw";
import { boot } from "../main";
import { queryClient } from "../shared/queries";
import type { ScreenProps } from "../shared/ctx";
import { calls, click, flush, installFetch, json, serve, text } from "../test/fakeServer";
import { installMedia } from "../test/meFixture";
import { LOADERS, SCREENS } from "./registry";

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
