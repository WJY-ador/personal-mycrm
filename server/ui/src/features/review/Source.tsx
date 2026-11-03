// 근거 원문 — 근거 구절이 든 문단 ±1(나머지는 흐리게) + 「전체 원문 보기」. 구절이 원문에 없으면 경고(결정 버튼은 잠긴 채),
// 문단 경계에 걸치면 전체 원문만. 원문을 못 받으면 경고(결정 잠김). 옛 app.html renderReview 의 fetchRec 갈래 그대로.
import type { ReactNode } from "react";
import type { ApiError } from "../../shared/api";
import { md, mdhm } from "../../shared/date";
import { Doc } from "../../shared/Doc";
import { splitDoc } from "../../shared/docParts";
import type { Journal } from "../../shared/journal";
import { Para } from "../../shared/Para";
import { oldSrc, srcText } from "../../shared/source";
import type { AppState, Cand } from "../../shared/state";
import { Tech } from "../../shared/Tech";
import { FIXHINT, type Words } from "./text";
import css from "./Review.module.css";

// 근거를 확인했다 = 원문을 받았고 구절이 원문에 있다(문단 경계에 걸쳐도 확인) — 이때만 결정 버튼이 켜진다
export const quoteOk = (j: Journal | undefined, c: Cand) => !!j && String(j.body).includes(c.quote);

type Props = { S: AppState; c: Cand; j?: Journal; fail: ApiError | null; w: Words };

export function Source({ S, c, j, fail, w }: Props) {
  const head = (t: string, meta?: string) => (
    <div className={css.srchead}><h3 id="source-title">{t}</h3>{meta && <span className="recmeta">{meta}</span>}</div>
  );
  let body: ReactNode;
  if (fail) {
    body = <>{head("근거 원문")}<div className={css.warn}><b>원문을 불러오지 못했어요. 근거를 확인할 수 없어 남길 수 없어요.</b> {FIXHINT}<Tech err={fail} /></div></>;
  } else if (!j) {
    body = <>{head("근거 원문")}<div className="doc"><p className="dim">원문을 불러오는 중이에요…</p></div></>;
  } else {
    const quote = c.quote;
    const qText = (id: string) => (S.questions || []).find(q => q.id === id)?.text || null;
    const rec = (S.journal || []).find(r => r.id === c.record_id);
    const old = oldSrc(j.meta.source);
    const line = srcText(S.sources, rec?.source_id ?? null) + (old ? ` · ${w.oldMark} 「${old}」` : "");
    const full = <Doc title={j.title} body={j.body} quote={quote} qText={qText} />;
    const tech = <details className="tech"><summary>기술 정보</summary>{`만든 시각 ${mdhm(j.meta.created)} · 출처 ${line} · 근거 구절 ${quote.length}자`}</details>;
    const meta = head(`근거 원문 · ${j.title}`, md(j.meta.created));
    const d = splitDoc(j.body, j.title);
    const at = d.paras.findIndex(p => p.includes(quote));
    if (!quoteOk(j, c)) {
      body = <>{meta}<div className={css.warn}><b>{w.mismatch}</b> 찾던 구절: <q>{quote}</q></div>{full}{tech}</>;
    } else if (at < 0) {
      body = <>{meta}<div className={css.note}>근거 구절이 문단 경계에 걸쳐 있어 위치를 강조하지 못했어요. 전체 원문에서 확인해 주세요.</div>{full}{tech}</>;
    } else {
      const lo = Math.max(0, at - 1), hi = Math.min(d.paras.length - 1, at + 1);
      body = (
        <>{meta}
          <div className="doc">{d.paras.slice(lo, hi + 1).map((p, i) => lo + i === at ? <Para key={i} p={p} quote={quote} /> : <Para key={i} p={p} dim />)}</div>
          <details className={`fold ${css.fold}`}><summary>전체 원문 보기</summary>{full}</details>{tech}</>
      );
    }
  }
  return <section className={css.src} id="rvsrc" aria-labelledby="source-title">{body}</section>;
}
