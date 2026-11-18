// 웹 대화 답 전용 — 줄 단위의 작은 markdown 렌더러. answer_get(server/answer.py _markdown)이 만드는 꼴만 블록으로 그린다:
// '## '(h3), '### '(h4), '> ' 연속 줄(blockquote), '- '·'* ' 연속 줄(ul), 빈 줄 = 문단 나눔, 그 밖 = 문단(줄바꿈 유지).
// 줄 안은 rich()(**굵게**)만. 표·링크·이미지·코드는 하지 않는다 — 코드 울타리(```) 줄과 그 안은 글자 그대로 문단.
// 모든 글자는 React 텍스트 노드(HTML 로 해석하지 않는다). 이스케이프 풀기는 answer.py _md_escape 의 거꾸로:
// 줄 처음(블록 기호를 뗀 뒤)의 '&#32;' → 공백, 앞 공백 뒤 '\' + ASCII 문장 부호 → 그 글자(정렬 목록 꼴은 숫자 뒤 '\.' '\)').
// 소제목은 _md_heading 이 끝 '#' 앞에 붙인 '\' 도 푼다. 그 밖의 백슬래시는 그대로 둔다.
import { Fragment, type ReactNode } from "react";
import { rich } from "../../shared/rich";

type Block =
  | { k: "h3" | "h4"; text: string }
  | { k: "quote"; lines: string[] }
  | { k: "ul"; items: string[][] }
  | { k: "p"; lines: string[]; raw: boolean };   // raw = 코드 울타리(이스케이프 풀기·굵게 없이 글자 그대로)

const LINE_SPLIT = /\r\n|\r|\n/;
const HEAD = /^ {0,3}(#{2,3}) (.*)$/s;            // '## ' · '### ' 만. '#' 하나와 4개 이상은 보통 글
const QUOTE = /^ {0,3}>(?: (.*))?$/s;              // '> 글' · '>' 만 있는 줄(인용 안 빈 줄)
const ITEM = /^ {0,3}[-*] (.*)$/s;
const CONT = /^ {2,}\S/;                          // 목록 항목에 붙는 이어지는 줄(2칸 이상 들여씀)
const FENCE = /^ {0,3}(`{3,}|~{3,})/;
const BLANK = /^[ \t]*$/;
const ESC = /^([ \t]*)(?:(\d{1,9})\\([.)])|\\([!-/:-@[-`{-~]))/;   // 앞 공백 + ('1\.' 꼴 | '\' + ASCII 문장 부호)
const HEAD_TAIL = /\\(#+)$/;

/** 줄 처음의 이스케이프 하나를 푼다(answer.py _md_escape 의 거꾸로). */
export function unescapeLine(s: string): string {
  if (s.startsWith("&#32;")) return " " + s.slice(5);
  const m = ESC.exec(s);
  if (!m) return s;
  return m[1] + (m[2] !== undefined ? m[2] + m[3] : m[4]) + s.slice(m[0].length);
}

function parse(text: string): Block[] {
  const out: Block[] = [];
  let cur: Block | null = null;
  let fence: { mark: string; block: Block & { k: "p" } } | null = null;
  const close = () => { cur = null; };
  for (const line of text.split(LINE_SPLIT)) {
    if (fence) {
      fence.block.lines.push(line);
      const f = FENCE.exec(line);
      if (f && f[1][0] === fence.mark[0] && f[1].length >= fence.mark.length && BLANK.test(line.slice(f[0].length))) fence = null;
      continue;
    }
    if (BLANK.test(line)) { close(); continue; }
    const c = cur as Block | null;
    if (c?.k === "ul" && CONT.test(line)) { c.items[c.items.length - 1].push(line.replace(/^ +/, "")); continue; }
    const f = FENCE.exec(line);
    if (f) {
      const block = { k: "p" as const, lines: [line], raw: true };
      out.push(block); fence = { mark: f[1], block }; close(); continue;
    }
    const h = HEAD.exec(line);
    if (h) { out.push({ k: h[1].length === 2 ? "h3" : "h4", text: h[2] }); close(); continue; }
    const q = QUOTE.exec(line);
    if (q) {
      const body = q[1] ?? "";
      if (c?.k === "quote") c.lines.push(body); else { cur = { k: "quote", lines: [body] }; out.push(cur); }
      continue;
    }
    const it = ITEM.exec(line);
    if (it) {
      if (c?.k === "ul") c.items.push([it[1]]); else { cur = { k: "ul", items: [[it[1]]] }; out.push(cur); }
      continue;
    }
    if (c?.k === "p" && !c.raw) c.lines.push(line); else { cur = { k: "p", lines: [line], raw: false }; out.push(cur); }
  }
  return out;
}

/** 줄 여러 개 → 줄마다 이스케이프 풀기 + 굵게, 사이는 "\n"(pre-wrap 으로 줄바꿈이 보인다). */
function lines(ls: string[], key: string, raw = false): ReactNode[] {
  const out: ReactNode[] = [];
  ls.forEach((l, i) => {
    if (i) out.push("\n");
    out.push(raw ? l : <Fragment key={`${key}.${i}`}>{rich(unescapeLine(l), `${key}.${i}.`)}</Fragment>);
  });
  return out;
}

export function answerMd(text: string, key: string): ReactNode {
  return parse(String(text ?? "")).map((b, i) => {
    const k = `${key}.${i}`;
    switch (b.k) {
      case "h3": case "h4": {
        const Tag = b.k;
        return <Tag key={k}>{rich(unescapeLine(b.text).replace(HEAD_TAIL, "$1"), `${k}.`)}</Tag>;
      }
      case "quote": return <blockquote key={k}>{lines(b.lines, k)}</blockquote>;
      case "ul": return <ul key={k}>{b.items.map((it, j) => <li key={`${k}.${j}`}>{lines(it, `${k}.${j}`)}</li>)}</ul>;
      case "p": return <p key={k}>{lines(b.lines, k, b.raw)}</p>;
    }
  });
}
