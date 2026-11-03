// 원문 대화창(옛 openRec·#dlg) — 기록 본문 한 편(/api/journal, 「나」·판단 검토와 같은 조회 키 = 캐시 하나) + 인용 구간 mark.
// 쓰는 화면이 useRecDialog() 로 열고, 돌려받은 요소를 그 화면에 한 번 그린다. 닫기 = 닫기 버튼·Esc(브라우저 기본).
import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiErr } from "./api";
import { mdhm, md } from "./date";
import { Doc } from "./Doc";
import { fetchJournal, journalKey } from "./journal";
import { PartFail } from "./PartFail";
import { srcLine } from "./source";
import type { AppState, Rec } from "./state";

// 글 이름 한 줄(옛 recLabel) — 없는 글·읽지 못한 글·「제목 · 날짜」
export function recLabel(S: AppState, id: string) {
  const r = (S.journal || []).find(j => j.id === id);
  return !r ? "찾을 수 없는 글" : r.broken ? "읽지 못한 글" : `${r.title} · ${md(r.created)}`;
}

function Body({ S, id, quote }: { S: AppState; id: string; quote: string }) {
  const q = useQuery({ queryKey: journalKey(id), queryFn: () => fetchJournal(id) });
  const r = q.data, rec: Rec | undefined = (S.journal || []).find(j => j.id === id);
  const qText = (qid: string) => (S.questions || []).find(x => x.id === qid)?.text || null;
  return (
    <>
      <div className="dh"><div><b id="rec-dlg-title">{r ? r.title : recLabel(S, id).split(" · ")[0]}</b>
        <div className="recmeta" style={{ margin: "2px 0 0" }}>{r ? `${mdhm(r.meta.created)} · ${srcLine(S.sources, rec?.source_id || null, r.meta.source)}` : ""}</div></div>
        <button className="small" type="button" data-close>닫기</button></div>
      <div className="db">{q.isError ? <PartFail err={apiErr(q.error)} what="이 글" />
        : !r ? <p style={{ color: "var(--muted)" }}>원문을 불러오는 중이에요…</p>
        : <Doc title={r.title} body={r.body} quote={quote} qText={qText} />}</div>
    </>
  );
}

export function useRecDialog(S: AppState) {
  const ref = useRef<HTMLDialogElement>(null);
  const [at, setAt] = useState<{ id: string; quote: string } | null>(null);
  useEffect(() => { const d = ref.current; if (at && d && !d.open) d.showModal?.(); }, [at]);
  const close = () => { ref.current?.close?.(); setAt(null); };
  const dialog = (
    <dialog ref={ref} className="recdlg" aria-labelledby="rec-dlg-title" onClose={() => setAt(null)}
      onClick={e => { if ((e.target as HTMLElement).closest("[data-close]")) close(); }}>
      {at ? <Body key={at.id} S={S} id={at.id} quote={at.quote} /> : null}
    </dialog>
  );
  return { open: (id: string, quote = "") => setAt({ id, quote }), dialog };
}
