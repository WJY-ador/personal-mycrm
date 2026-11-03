// 축 하나(옛 renderAxis) — 이 축의 활동 · 내 글 · 이 축을 가리키는 판단·기준(문맥 API /api/axes/{id}/context). 링크는 주소만(글 = 「나」, 항목 = 옛 주소 → 새 자리)
import { useQuery } from "@tanstack/react-query";
import { apiErr } from "../../shared/api";
import { ActRows } from "../../shared/ActRows";
import { md } from "../../shared/date";
import { LoadFail } from "../../shared/LoadFail";
import type { AppState } from "../../shared/state";
import { actApi } from "./actApi";
import { LOADING } from "./text";

export function AxisView({ S, id }: { S: AppState; id: string }) {
  const q = useQuery({ queryKey: ["activity", "axis", id], queryFn: () => actApi.axis(id) });
  if (q.isError) return <LoadFail err={apiErr(q.error)} what="축" />;
  if (!q.data) return <p className="hint">{LOADING}</p>;
  const j = q.data, xs = j.activities || [], recs = j.records || [], its = j.items || [];
  const def = (oid: string) => (S.definitions || []).find(d => d.id === oid);
  return (
    <>
      <div className="eyebrow">축</div><h2 className="title">{j.axis?.title || "(제목 없음)"}</h2>
      <h2 className="sh">활동 <span className="speclabel">{j.activity_count}</span></h2><ActRows xs={xs} actions={S.activity_ui?.actions} empty="이 축의 활동이 없어요." />
      {j.activity_count > xs.length ? <p className="hint">{`최근 ${xs.length}건만 보여요. `}<a href={`#_obj/activity/list/axis=${encodeURIComponent(id)}`}>모두 보기</a></p> : null}
      <h2 className="sh">내 글 <span className="speclabel">{recs.length}</span></h2>
      {recs.length ? <ul className="mini">{recs.map(r => <li key={r.id}><a href={`#_me/journal/${r.id}`}>{r.title || "(제목 없음)"}</a>{r.created ? <span className="tech">{md(r.created)}</span> : null}</li>)}</ul>
        : <div className="empty">이 축에 붙은 글이 없어요.</div>}
      <h2 className="sh">이 축을 가리키는 판단·기준 <span className="speclabel">{its.length}</span></h2>
      {its.length ? <ul className="mini">{its.map(it => {
        const d = def(it.object_id), f = (d?.fields || []).find(x => x.key === it.field_key);
        return <li key={it.id}><a href={`#structure/${it.object_id}/${it.id}`}>{it.title || "(제목 없음)"}</a>
          <span className="tech">{d?.label || "항목"}{it.field_key ? ` · ${f ? f.label : it.field_key}` : ""}</span></li>;
      })}</ul> : <div className="empty">없어요.</div>}
    </>
  );
}
