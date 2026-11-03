// rich()·문단 — rich.cases.json(옛 JS 시험 server/test_ui_alignment.py 와 같은 사례). 결과는 요소 트리로 본다(HTML 문자열을 만들지 않는다).
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, test } from "vitest";
import cases from "./rich.cases.json";
import { rich } from "./rich";
import { Para } from "./Para";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

function draw(node: React.ReactNode): HTMLElement {
  const el = document.createElement("div");
  act(() => createRoot(el).render(node));
  return el;
}
// 조각 = [태그, 글자] — 글자 노드는 "", 요소는 소문자 태그 이름. 요소 안은 글자만(중첩 없음)
const parts = (el: Element) => [...el.childNodes].map(n => [n.nodeType === 3 ? "" : n.nodeName.toLowerCase(), n.textContent]);

test("rich — 사례 전부 · 요소는 strong 뿐", () => {
  for (const c of cases.rich) {
    const el = draw(<p>{rich(c.in)}</p>).firstElementChild!;
    expect(parts(el), c.in).toEqual(c.out);
    expect([...el.querySelectorAll("*")].every(x => x.nodeName === "STRONG"), c.in).toBe(true);
  }
});

test("문단 — 머리 줄(.h) · 인용 mark · 굵게", () => {
  for (const c of cases.para) {
    const p = draw(<Para p={c.in} quote={c.quote} />).firstElementChild!;
    expect(p.className, c.in).toBe(c.h ? "h" : "");
    expect(parts(p), c.in).toEqual(c.out);
  }
});
