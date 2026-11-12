// 사람 문맥(옛 personCtx) — 연결된 활동(최근 N, 더 있으면 「모두 보기」) · 옛 판 연결 안내(휴지통 꺼짐) · 연결된 글 · 이 사람을 가리키는 항목.
// 링크는 주소만 — 글 = 「나」 글 상세, 항목 = 옛 항목 주소(껍데기가 새 자리로 옮긴다)
import { useQuery } from "@tanstack/react-query";
import { ActRows } from "../../shared/ActRows";
import { apiErr } from "../../shared/api";
import { md } from "../../shared/date";
import { LoadFail } from "../../shared/LoadFail";
import type { AppState } from "../../shared/state";
import { trashOn } from "./model";
import { objApi } from "./objApi";
import { LOADING } from "./text";

export function PersonCtx({ S, id }: { S: AppState; id: string }) {
  const q = useQuery({ queryKey: ["objects", "person", id], queryFn: () => objApi.person(id) });
  if (q.isError && !q.data) return <LoadFail err={apiErr(q.error)} what="연결된 활동과 글" />;
  if (!q.data) return <p className="hint">{LOADING}</p>;
  const j = q.data, xs = j.activities || [], recs = j.records || [], its = j.items || [];
  const def = (oid: string) => (S.definitions || []).find(d => d.id === oid);
  return (
    <>
      {q.isError ? <LoadFail err={apiErr(q.error)} what="연결된 활동과 글" /> : null}
      <h2 className="sh">연결된 활동 <span className="speclabel">{j.activity_count}</span></h2><ActRows xs={xs} actions={S.activity_ui?.actions} empty="연결된 활동이 없어요." />
      {j.old_revision_links && !trashOn(S) ? <p className="hint">옛 판 활동 연결이 {j.old_revision_links}개 있어 지울 수 없어요.</p> : null}
      {j.activity_count > xs.length ? <p className="hint">{`최근 ${xs.length}건만 보여요. `}<a href={`#_obj/activity/list/person=${encodeURIComponent(id)}`}>모두 보기</a></p> : null}
      <h2 className="sh">연결된 글 <span className="speclabel">{recs.length}</span></h2>
      {recs.length ? <ul className="mini">{recs.map(r => <li key={r.id}><a href={`#_me/journal/${r.id}`}>{r.title || "(제목 없음)"}</a>{r.created ? <span className="tech">{md(r.created)}</span> : null}</li>)}</ul>
        : <div className="empty">연결된 글이 없어요.</div>}
      <h2 className="sh">이 사람을 가리키는 항목 <span className="speclabel">{its.length}</span></h2>
      {its.length ? <ul className="mini">{its.map(it => {
        const d = def(it.object_id), f = (d?.fields || []).find(x => x.key === it.field_key);
        return <li key={it.id}><a href={`#structure/${it.object_id}/${it.id}`}>{it.title || "(제목 없음)"}</a>
          <span className="tech">{d?.label || "항목"}{it.field_key ? `, ${f ? f.label : it.field_key}` : ""}</span></li>;
      })}</ul> : <div className="empty">없어요.</div>}
    </>
  );
}
