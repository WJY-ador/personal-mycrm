// 내 구조 설정(옛 test_web_home test_static_moved A3 절·test_ui_alignment 를 옮김, R5b-1) — 그래프 기본 · 목록 전환 · 서버 SVG 를 React 요소로(script·on*·바깥 링크 0) ·
// 원·선 → 목록의 같은 앵커(주소 그대로) · 출처 칩 = 서버 origin_labels · 이름 공유(껍데기 메뉴 문구) · 편입 미리보기·보류·거절·편입 확인창(체크해야 켜짐).
import { act } from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { queryClient } from "../../shared/queries";
import { calls, click, installFetch, json, serve, text } from "../../test/fakeServer";
import { byText, hideScreen, reload, showScreen } from "../../test/showScreen";
import { PREVIEW, structState } from "../../test/structFixture";

let POST: (url: string) => Response = () => json(200, {});
beforeEach(() => {
  installFetch(); queryClient.clear(); reload.mockClear(); POST = () => json(200, {});
  serve((url, m) => (m === "POST" ? POST(url) : url === "/api/std/preview" ? json(200, PREVIEW) : json(404, {})));
});
afterEach(() => { hideScreen(); document.getElementById("acct-menu")?.remove(); vi.unstubAllGlobals(); });
const show = (s: object = structState()) => showScreen("defs", "#_setup/structure", [], s);
const posts = () => calls.filter(c => c.method === "POST").map(c => ({ url: c.url, body: c.body }));

test("그래프 기본 · 서버 SVG = React 요소(script·on*·javascript: 링크 0, 스타일·속성 유지) · 원 누르면 목록 앵커로(주소 그대로)", async () => {
  const el = await show();
  expect(el.querySelector('[aria-pressed="true"]')!.textContent).toBe("그래프");
  expect(el.querySelector("#dlist")!.hasAttribute("hidden")).toBe(true);
  const svg = el.querySelector(".dmo svg")!;
  expect(svg.namespaceURI).toBe("http://www.w3.org/2000/svg");
  expect(svg.getAttribute("viewBox")).toBe("0 0 100 100");
  expect(svg.querySelector("script")).toBeNull();
  expect(svg.querySelector("circle")!.getAttribute("onclick")).toBeNull();
  expect(svg.querySelector("circle")!.getAttribute("stroke-width")).toBe("1.6");
  expect((svg.querySelector("circle") as SVGElement).style.stroke).toBe("red");
  expect(svg.querySelector("text")!.getAttribute("text-anchor")).toBe("middle");
  expect([...svg.querySelectorAll("a")].map(a => a.getAttribute("href"))).toEqual(["#dmo-o1", null, "#dmo-r1"]);
  expect(svg.querySelectorAll("title").length).toBe(2);   // SVG 안 title 은 문서 머리로 옮기지 않는다
  expect(text(el, ".dlegend span")).toEqual(["표준", "커스텀", "점선 고리 = 표준 정의 보호", expect.stringContaining("세 갈래")]);
  location.hash = "#_setup/structure";
  await act(async () => { svg.querySelector("circle")!.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true })); });
  expect(location.hash).toBe("#_setup/structure");
  expect(el.querySelector("#dlist")!.hasAttribute("hidden")).toBe(false);
  expect(el.querySelector("#dmo-o1")!.className).toContain("dmo-hit");
  expect(document.activeElement!.id).toBe("dmo-o1");
});

test("목록 — 자료 종류 카드(출처 칩 = 서버 라벨 · 보호 · 표준명 · 종류 · 항목 수) · 필드 표 · 관계 · 공통 대상", async () => {
  const el = await show();
  await click(byText(el, "button", "목록")[0]);
  expect(text(el, ".sobj h3")).toEqual(["기준", "숙제"]);
  expect(text(el, "#dmo-o1 .labels .chip")).toEqual(["표준", "표준 정의 보호", "표준 기준", "기준", "항목 2"]);
  expect(el.querySelector("#dmo-o2 .labels .chip")!.className).toBe("chip o-tpl");
  expect(text(el, "#dmo-o1 thead th")).toEqual(["필드", "키", "값", "구분", "보호"]);
  expect(text(el, "#dmo-o1 tbody td")[2]).toBe("참조 → 검토할 판단 N:N");
  expect(el.querySelector("#dmo-r1")!.textContent).toContain("기준근거 → 검토할 판단");
  expect(el.querySelector("#dmo-core-candidate")!.textContent).toBe("검토할 판단");
  expect(el.querySelector(".srel + .hint, .sec .hint")!.textContent).toContain("검토할 판단을 가리키는 관계가 있어요.");
});

test("이름 공유 — 껍데기 메뉴(사용자 구간)가 있을 때만 · 문구는 메뉴에서 · 켜기 = 같은 API", async () => {
  let el = await show();
  expect(el.querySelector("#names-h")).toBeNull();
  const menu = document.createElement("div");
  menu.id = "acct-menu";
  const item = document.createElement("button"), note = document.createElement("p"), a = document.createElement("a");
  item.id = "acct-names"; item.append("구조 이름 공유 ", Object.assign(document.createElement("span"), { textContent: "꺼짐" }));
  note.className = "acct-note"; a.href = "/privacy#privacy-1"; a.setAttribute("onclick", "x()"); a.textContent = "무엇을 보나요";
  note.append("안 해도 모든 기능을 써요. ", a); menu.append(item, note);   // 껍데기 계정 메뉴(사용자 구간) 흉내
  document.body.append(menu);
  hideScreen();
  el = await show();
  expect(el.querySelector("#names-h")!.textContent).toBe("구조 이름 공유");
  const link = el.querySelector("#names-h + .hint a")!;
  expect([link.getAttribute("href"), link.getAttribute("onclick")]).toEqual(["/privacy#privacy-1", null]);
  await click(byText(el, "button", "구조 이름 공유 꺼짐")[0]);
  expect(posts()).toEqual([{ url: "/api/optional-consent", body: { kind: "struct_names", on: true } }]);
  expect(reload).toHaveBeenCalled();
});

test("편입 미리보기 — 카드 · 보류(서버 state 그대로) → 머리 한 줄 + 다시 받기 · 편입 = 확인창 체크 뒤 confirmed_meaning·revision · 실패 = 그 카드 문구", async () => {
  const el = await show();
  const cards = el.querySelectorAll(".spvc");
  expect(text(el, ".spvc h4")).toEqual(["표준 기준처음부터 표준", "표준 축아직 고르지 않음", "표준 결정보류"]);
  expect(cards[0].querySelector(".hint")!.textContent).toBe("이미 표준으로 쓰고 있어요.");
  expect(cards[2].querySelector(".blocked")!.textContent).toBe("편입할 수 없어요. 구조가 표준과 달라요. 대화로 정의를 표준 모양에 맞춘 뒤 다시 보세요.");
  expect(cards[2].textContent).toContain("표준 필드 rules 가 없어요");
  expect((byText(cards[2] as Element, "button", "보류")[0] as HTMLButtonElement).disabled).toBe(true);
  await click(byText(cards[1] as Element, "button", "보류")[0]);
  expect(posts()).toEqual([{ url: "/api/std/choose", body: { std_key: "axes", state: "deferred" } }]);
  expect(el.querySelector("#std-msg")!.textContent).toBe("표준 축: 보류로 남겼어요. 다른 기능은 그대로예요.");
  expect(reload).toHaveBeenCalledTimes(1);
  // 편입 — 확인창: 체크 전엔 [편입하기] 꺼짐
  await click(byText(el, "button", "편입…")[0]);
  const dlg = el.querySelector("#std-dlg")!;
  expect(dlg.querySelector("#std-dlg-title")!.textContent).toBe("표준 축으로 편입하기");
  expect(dlg.querySelector(".stdok span")!.textContent).toBe("이 자료 종류를 표준 축과 같은 뜻으로 써요. 아래 잠금 영향을 확인했어요.");
  expect(text(dlg, "ul li")).toEqual(["자료 종류 삭제, 보관", "표준 필드 빼기"]);
  const go = byText(dlg, "button", "편입하기")[0] as HTMLButtonElement;
  expect(go.disabled).toBe(true);
  await click(dlg.querySelector('input[type="checkbox"]'));
  expect(go.disabled).toBe(false);
  POST = () => json(400, { code: "STANDARD-LOCKED", msg: "x" });
  await click(go);
  expect(posts().at(-1)).toEqual({ url: "/api/std/choose", body: { std_key: "axes", state: "incorporated", confirmed_meaning: true, expected_revision: 4 } });
  expect(el.querySelectorAll(".spvc")[1].querySelector(".perror")!.textContent).toBe("이미 편입된 표준은 보류나 거절로 바꿀 수 없어요.");
  POST = () => json(400, { code: "CONFLICT", msg: "x" });
  await click(byText(el.querySelectorAll(".spvc")[1] as Element, "button", "거절")[0]);
  expect(el.querySelector("#std-msg")!.textContent).toBe("표준 축: 다른 곳에서 먼저 바뀌었어요. 미리보기를 다시 불러왔어요. 다시 확인해 주세요.");
});

test("미리보기 못 읽음 · 구조 정의 없음", async () => {
  serve(() => json(500, { code: "X", msg: "m" }));
  let el = await show();
  expect(el.querySelector("#std-pv .partfail b")!.textContent).toBe("편입 미리보기을 읽지 못했어요. 나머지는 정상이에요.");
  el = await show(structState({ structure: null }));
  expect(el.textContent).toBe("구조 정의를 읽지 못했어요. 새로 고침해도 그대로면 다시 로그인해 보세요.");
});
