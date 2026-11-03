// 문단 하나 — 「#」 머리 줄은 머리 문단(.h), 인용(quote)이 있으면 처음 한 곳을 <mark>(옛 app.html paraHtml 과 같음. 사례 = rich.cases.json)
import { rich } from "./rich";

export function Para({ p, quote }: { p: string; quote?: string }) {
  const isH = /^#{1,6}\s/.test(p);
  const text = isH ? p.replace(/^#{1,6}\s+/, "") : p;
  const i = quote ? text.indexOf(quote) : -1;
  const inner = quote && i >= 0
    ? [...rich(text.slice(0, i), "a"), <mark key="m">{rich(quote, "q")}</mark>, ...rich(text.slice(i + quote.length), "b")]
    : rich(text);
  return <p className={isH ? "h" : ""}>{inner}</p>;
}
