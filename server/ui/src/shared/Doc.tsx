// 기록 본문 — 문단(굵게·인용 mark) + 「이 글이 붙는 곳」 표. 글자는 전부 텍스트 노드(HTML 로 해석하지 않는다)
import { attachRows, splitDoc } from "./docParts";
import { Para } from "./Para";

type Props = { title: string | null; body: string; quote?: string; qText: (id: string) => string | null };

export function Doc({ title, body, quote, qText }: Props) {
  const d = splitDoc(body, title);
  const rows = attachRows(d.attach, qText);
  return (
    <div className="doc">
      {d.paras.map((p, i) => <Para key={i} p={p} quote={quote} />)}
      {rows.length > 0 && (
        <div className="attach">
          <h4>이 글이 붙는 곳</h4>
          <dl>{rows.map(([k, v], i) => [<dt key={`t${i}`}>{k}</dt>, <dd key={`d${i}`}>{v}</dd>])}</dl>
        </div>
      )}
    </div>
  );
}
