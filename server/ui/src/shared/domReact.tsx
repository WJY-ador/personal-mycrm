// 서버가 만든 마크업(구조 그래프 SVG · 껍데기 메뉴 안내 한 줄)을 React 요소로 옮긴다 — HTML 로 해석해 꽂지 않는다(HTML 문자열 꽂기 0).
// 글자는 텍스트 노드로만. 막는 것: script·foreignObject·style·iframe·object 요소 · on* 속성 · 「#」·「/」로 시작하지 않는 링크(javascript: 등).
import { createElement, type ReactNode } from "react";

const DROP = new Set(["script", "foreignobject", "style", "iframe", "object", "embed"]);
const camel = (n: string) => n.replace(/[-:]([a-z])/g, (_, c: string) => c.toUpperCase());

function attrs(el: Element, key: string): Record<string, unknown> {
  const out: Record<string, unknown> = { key };
  for (const a of [...el.attributes]) {
    const n = a.name.toLowerCase(), v = a.value;
    if (n.startsWith("on")) continue;
    if (n === "href" || n === "xlink:href") { if (/^[#/](?!\/)/.test(v)) out.href = v; continue; }
    if (n === "class") out.className = v;
    else if (n === "style") out.style = Object.fromEntries(v.split(";").map(d => d.split(/:(.*)/s).map(x => x.trim())).filter(d => d[0] && d[1])
      .map(([k, x]) => [k.startsWith("--") ? k : camel(k), x]));
    else if (n.startsWith("aria-") || n.startsWith("data-") || n === "role" || n === "viewbox") out[n === "viewbox" ? "viewBox" : n] = v;
    else if (n === "xmlns" || n.startsWith("xmlns:")) continue;
    else out[camel(n)] = v;
  }
  return out;
}

export function domToReact(node: Node, key = "n"): ReactNode {
  if (node.nodeType === 3) return node.nodeValue;
  if (node.nodeType !== 1) return null;
  const el = node as Element, tag = el.tagName.toLowerCase().replace(/^svg:/, "");
  if (DROP.has(tag)) return null;
  const kids = [...el.childNodes].map((c, i) => domToReact(c, `${key}.${i}`)).filter(k => k !== null && k !== "");
  const name = el.namespaceURI === "http://www.w3.org/2000/svg" ? el.localName : tag;
  return createElement(name, attrs(el, key), ...kids);
}

// SVG 문자열 → React 요소(파싱 실패·루트가 svg 가 아니면 null)
export function svgToReact(svg: string): ReactNode {
  if (!svg) return null;
  const doc = new DOMParser().parseFromString(svg, "image/svg+xml");
  const root = doc.documentElement;
  if (!root || root.localName !== "svg" || doc.getElementsByTagName("parsererror").length) return null;
  return domToReact(root, "svg");
}
