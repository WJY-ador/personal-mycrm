// 자동 분류 항목의 근거 원문(2026-11-18 구조추천 명세 6.5) — 기록 제목 링크 + 단위 구간 글 그대로. 글은 글자로만 그린다(서식 해석, HTML 없음).
// 원문이 휴지통이면 서버가 text, record_title 을 null 로 준다.
import { useQuery } from "@tanstack/react-query";
import { meApi } from "./meApi";
import { ROUTE_TEXT as T } from "./text";

export function RouteSrc({ id, at }: { id: string; at: string }) {
  const q = useQuery({ queryKey: ["me", "route", id, at], queryFn: () => meApi.routeItem(id) });
  const x = q.data?.item;
  const body = q.isError ? <span className="hint">{T.fail}</span> : !q.data ? <span className="hint">{T.loading}</span> : !x ? null
    : x.text === null ? <span className="hint">{T.gone}</span>
    : <><a href={`#_me/journal/${encodeURIComponent(x.record_id)}`}>{x.record_title || "(제목 없음)"}</a>{x.unit_key ? <span className="tech"> {x.unit_key}</span> : null}
      <blockquote className="reco-quote">{x.text}</blockquote></>;
  return <dl className="kv" id="route-src"><dt>{T.src}</dt><dd>{body}</dd></dl>;   // 필드 줄(FieldRows)과 같은 꼴
}
