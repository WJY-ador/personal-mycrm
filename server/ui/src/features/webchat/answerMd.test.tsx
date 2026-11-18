// answerMd — 웹 대화 답의 작은 markdown 렌더러. FULL 은 server/answer.py _markdown 이 가짜 자료로 실제로 낸 글(이스케이프 포함) 그대로다.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, test } from "vitest";
import { answerMd, unescapeLine } from "./answerMd";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

function draw(text: string): HTMLElement {
  const el = document.createElement("div");
  act(() => createRoot(el).render(<div>{answerMd(text, "t1")}</div>));
  return el.firstElementChild as HTMLElement;
}
const tags = (el: Element) => [...el.children].map(c => c.nodeName.toLowerCase());
const texts = (el: Element, sel: string) => [...el.querySelectorAll(sel)].map(x => x.textContent);

const FULL = "## C# 도입은 어떻게 \\#\n\n### 답변 초안\n\n> 첫 문장이다.\n> \\- 줄머리 하이픈\n> \\#태그로 시작\n> 1\\. 숫자 목록\n"
  + "> &#32;   네 칸 들여쓰기\n> \\<img src=x onerror=alert(1)> (r_aaaa)\n\n> 두 번째 **굵게** 인용. (r_bbbb)\n\n### 근거\n\n"
  + "- (r_aaaa) 가짜 제목 하나, 2026-11-01, 원문\n- (r_bbbb) 가짜 제목 둘, 2026-11-02, 세션 정리\n\n### 부족한 곳\n\n- 근거가 한 편뿐이에요.\n";

test("answer_get 꼴 한 벌 — h3 1 · h4 3 · blockquote 2 · li 3, 이스케이프 풀림", () => {
  const el = draw(FULL);
  expect(tags(el)).toEqual(["h3", "h4", "blockquote", "blockquote", "h4", "ul", "h4", "ul"]);
  expect(texts(el, "h3")).toEqual(["C# 도입은 어떻게 #"]);
  expect(texts(el, "h4")).toEqual(["답변 초안", "근거", "부족한 곳"]);
  expect(texts(el, "blockquote")).toEqual([
    "첫 문장이다.\n- 줄머리 하이픈\n#태그로 시작\n1. 숫자 목록\n    네 칸 들여쓰기\n<img src=x onerror=alert(1)> (r_aaaa)",
    "두 번째 굵게 인용. (r_bbbb)",
  ]);
  expect(texts(el, "li")).toEqual(["(r_aaaa) 가짜 제목 하나, 2026-11-01, 원문", "(r_bbbb) 가짜 제목 둘, 2026-11-02, 세션 정리", "근거가 한 편뿐이에요."]);
  expect(el.querySelectorAll("blockquote strong").length).toBe(1);
  expect(el.querySelector("img, a")).toBeNull();
});

test("이스케이프 풀기 — 줄 처음만", () => {
  expect(unescapeLine("\\- 문장")).toBe("- 문장");
  expect(unescapeLine("\\#태그")).toBe("#태그");
  expect(unescapeLine("1\\. 문장")).toBe("1. 문장");
  expect(unescapeLine("12\\) 문장")).toBe("12) 문장");
  expect(unescapeLine("  \\> 들여쓴 인용 꼴")).toBe("  > 들여쓴 인용 꼴");
  expect(unescapeLine("&#32;   들여쓰기")).toBe("    들여쓰기");
  expect(unescapeLine("경로 C:\\-x 와 a\\#b")).toBe("경로 C:\\-x 와 a\\#b");   // 줄 가운데 백슬래시는 그대로
  expect(unescapeLine("\\가")).toBe("\\가");                                // 문장 부호가 아니면 그대로
  expect(unescapeLine("1\\- x")).toBe("1\\- x");                            // 숫자 뒤는 '.' ')' 만
});

test("문단·목록 줄의 이스케이프도 풀린다", () => {
  const el = draw("\\- 문단 첫 줄\n\\#둘째 줄\n\n- \\* 항목");
  expect(tags(el)).toEqual(["p", "ul"]);
  expect(el.querySelector("p")!.textContent).toBe("- 문단 첫 줄\n#둘째 줄");
  expect(texts(el, "li")).toEqual(["* 항목"]);
});

test("HTML 꼴은 글자로만", () => {
  const el = draw("<img src=x onerror=alert(1)>\n\n> <script>x</script>\n\n- <b>굵게?</b>");
  expect(el.querySelector("img, script, b")).toBeNull();
  expect(el.textContent).toBe("<img src=x onerror=alert(1)>" + "<script>x</script>" + "<b>굵게?</b>");
});

test("앞 문장 뒤에 줄바꿈 없이 붙은 ## 는 제목이 아님", () => {
  const el = draw("찾아봤어요.## 질문\n\n### 답변 초안");
  expect(tags(el)).toEqual(["p", "h4"]);
  expect(el.querySelector("p")!.textContent).toBe("찾아봤어요.## 질문");
});

test("# 하나와 #### 는 보통 글, 앞 공백 3칸까지 제목", () => {
  const el = draw("# 하나\n\n#### 넷\n\n   ## 셋 칸");
  expect(tags(el)).toEqual(["p", "p", "h3"]);
  expect(texts(el, "h3")).toEqual(["셋 칸"]);
});

test("여러 줄 인용과 > 만 있는 줄", () => {
  const el = draw("> 첫 줄\n>\n> 셋째 줄 (r_1)");
  expect(tags(el)).toEqual(["blockquote"]);
  expect(el.textContent).toBe("첫 줄\n\n셋째 줄 (r_1)");
});

test("목록 이어지는 줄(2칸 이상)은 앞 항목에 붙는다", () => {
  const el = draw("- 하나\n  이어서\n* 둘");
  expect(texts(el, "li")).toEqual(["하나\n이어서", "둘"]);
});

test("\\r\\n · \\r 본문", () => {
  const el = draw("## 질문\r\n\r\n### 답변 초안\r\n\r\n> 가\r> 나 (r_1)\r\n");
  expect(tags(el)).toEqual(["h3", "h4", "blockquote"]);
  expect(el.querySelector("blockquote")!.textContent).toBe("가\n나 (r_1)");
});

test("굵게 유지", () => {
  const el = draw("앞 **굵게** 뒤\n\n- **항목** 하나");
  expect(texts(el, "strong")).toEqual(["굵게", "항목"]);
  expect(el.querySelector("p")!.textContent).toBe("앞 굵게 뒤");
});

test("코드 울타리 줄과 그 안은 글자 그대로 문단", () => {
  const el = draw("```\n## 제목 아님\n\n- 목록 아님\n\\- 그대로\n```\n\n## 질문");
  expect(tags(el)).toEqual(["p", "h3"]);
  expect(el.querySelector("p")!.textContent).toBe("```\n## 제목 아님\n\n- 목록 아님\n\\- 그대로\n```");
});

test("줄 안의 U+2028 은 줄 끝이 아니다 — 인용 줄이 문단으로 새지 않는다", () => {
  const el = draw("> 가 나 (r_1)");
  expect(tags(el)).toEqual(["blockquote"]);
  expect(el.textContent).toBe("가 나 (r_1)");
});

test("빈 문자열", () => {
  expect(tags(draw(""))).toEqual([]);
  expect(draw("").textContent).toBe("");
});
