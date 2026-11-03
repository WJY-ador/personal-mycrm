// 사용자 글 본문 전용 — 한 줄 안의 **굵게** 만 <strong>, 그 밖은 글자 그대로(React 텍스트 노드 — HTML 로 해석하지 않는다).
// 링크·이미지·그 밖 마크다운은 하지 않는다(옛 app.html rich · web.py 서버 쪽 규칙과 같음). 사례 = rich.cases.json(옛 JS 와 같이 통과).
import type { ReactNode } from "react";

const BOLD = /\*\*(.+?)\*\*/g;   // 「.」 은 줄바꿈을 넘지 않는다 — 여러 줄에 걸친 ** 는 그대로

export function rich(s: string | null | undefined, key = "r"): ReactNode[] {
  const t = String(s ?? "");
  const out: ReactNode[] = [];
  let at = 0, i = 0;
  for (const m of t.matchAll(BOLD)) {
    if (m.index > at) out.push(t.slice(at, m.index));
    out.push(<strong key={`${key}${i++}`}>{m[1]}</strong>);
    at = m.index + m[0].length;
  }
  if (at < t.length) out.push(t.slice(at));
  return out;
}
