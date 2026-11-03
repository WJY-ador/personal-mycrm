// 내 글 상세 — 제목·시각·출처·질문 + 동작 + 본문(문단·굵게) + 연결. 본문은 /api/journal(이어 받지 않은 글도 직접 링크로 열린다).
// 수기 수정(A0′): 제목·본문을 누르면 인라인 편집. 본문은 새 본문 전체를 보내고 서버가 공통 앞·뒤를 뺀 한 구간으로 바꾼다.
// 본문 [저장] = 먼저 서버 미리보기 — 지워질 검토할 판단이 있으면 그 문구를 그대로 보이고 [이대로 저장] 1번, 없으면 바로 저장.
// 막힘(내가 결정한 판단이 붙은 글·휴지통·revision 충돌)은 서버 msg·action 그대로. 남이 쓴 글(external)은 고치기를 보이지 않는다.
import { useQuery } from "@tanstack/react-query";
import { apiErr } from "../../shared/api";
import { mdhm } from "../../shared/date";
import { Doc } from "../../shared/Doc";
import { oldSrc } from "../../shared/source";
import type { Rec } from "../../shared/state";
import { Acts } from "./Acts";
import { Conn } from "./Conn";
import { useEdit, type EditSpec } from "../../shared/edit";
import { Editable } from "../../shared/Editable";
import { Editor } from "../../shared/Editor";
import { Head } from "./Head";
import { meApi, type Journal } from "./meApi";
import { qById, srcText, type World } from "./model";
import { GONE, LOADING, serverErrText } from "./text";
import { QK } from "./useWorld";
import css from "./Me.module.css";

function specs(j: Journal): [EditSpec, EditSpec] {
  return [
    { key: "rtitle:" + j.id, done: "제목을 바꿨어요.", errText: serverErrText,
      fields: [{ name: "title", label: "제목", multi: false, orig: j.title }], save: d => meApi.recordTitle(j.id, j.revision, d.title.trim()) },
    { key: "rbody:" + j.id, done: "본문을 고쳤어요.", errText: serverErrText,
      fields: [{ name: "body", label: "본문", multi: true, orig: j.body }], save: d => meApi.recordBody(j.id, j.revision, d.body),
      confirm: d => meApi.recordBodyPreview(j.id, j.revision, d.body).then(p => p.msg) },   // 지워질 판단이 있으면 서버 문구 + [이대로 저장] 1번
  ];
}

export function RecDetail({ W, id, x, trashOn }: { W: World; id: string; x: Rec | undefined; trashOn: boolean }) {
  const { editing } = useEdit();
  const q = useQuery({ queryKey: QK.journal(id), queryFn: () => meApi.journal(id) });
  const j = q.data;
  if (!x && q.isError) return <div className="empty">{GONE} <a href="#_me">목록으로</a></div>;
  if (!x && !j) return <p className="hint">{LOADING}</p>;
  const qn = x?.question_id ? qById(W, x.question_id) : null;
  const meta = x ? [mdhm(x.created), srcText(W, x.source_id), qn ? `질문 「${qn.text}」` : ""]
    : [mdhm(j!.meta.created), srcText(W, null) + (oldSrc(j!.meta.source) ? ` · 쓸 당시 표기 「${oldSrc(j!.meta.source)}」` : "")];
  const title = x ? x.title || x.excerpt || "(제목 없음)" : j!.title;
  const can = !!j && (x?.author_kind ?? j.author_kind) !== "external";
  const [ts, bs] = j ? specs(j) : [null, null];
  const fail = q.isError ? apiErr(q.error) : null;
  return (
    <>
      {ts && editing(ts.key) ? <><div className={css.kind}>내 글</div><Editor /></>
        : <Head kind="내 글" title={can && ts ? <Editable spec={ts} look="inline">{title}</Editable> : title} meta={meta.filter(Boolean).join(" · ")} />}
      {trashOn && <Acts W={W} r={{ k: "journal", id, title, kind: "내 글", at: x?.created || "", x: x || ({ id } as Rec) }} trashOn />}
      {fail ? <div className="partfail" role="alert"><b>이 글을 읽지 못했어요 · 나머지는 정상</b><p>{fail.code === "OFFLINE" ? "서버에 연결하지 못했어요." : "글이 지워졌거나 찾을 수 없어요."} 새로 고침해도 그대로면 다시 로그인해 보세요.</p></div>
        : !j ? <p className="hint">{LOADING}</p>
        : bs && editing(bs.key) ? <Editor />
        : can && bs ? <Editable spec={bs} block look="doc"><Doc title={j.title} body={j.body} qText={id2 => qById(W, id2)?.text || null} /></Editable>
        : <Doc title={j.title} body={j.body} qText={id2 => qById(W, id2)?.text || null} />}
      <Conn W={W} kind="journal" id={id} />
    </>
  );
}
