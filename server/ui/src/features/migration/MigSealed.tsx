// plan 확인 본문(옛 migPlanHtml) — 머리(plan·항목 수·시각·hash) · staged = 안내 + [취소] · 닫힘 = 안내 + 표 · sealed = 표·항목·기준 체크·[반영](확인창)·[취소].
// 스위치 꺼짐(on=false) = 기준 체크·[반영]·확인창 없이 안내 + [취소]. 확인창 숫자는 지금 체크 상태로 센다
import { useRef } from "react";
import type { ApiError } from "../../shared/api";
import { mdhm } from "../../shared/date";
import type { Detail, Limits, PItem } from "./migApi";
import { MigErr } from "./MigErr";
import { MigItem, type BodyState } from "./MigItem";
import { left, tally } from "./model";
import { MIG_ACT, MIG_ACTIONS, OFF } from "./text";
import { UnitTable } from "./UnitTable";
import { StateChip } from "./Why";
import css from "./Migration.module.css";

export type SealedProps = {
  pl: Detail; L: Limits | null; on: boolean; busy: boolean; err: ApiError | null; open: Set<number>; bodies: Record<number, BodyState>;
  onCheck: (x: PItem, v: boolean) => void; onBody: (x: PItem) => void; onApply: () => void; onCancel: () => void;
};

export function MigSealed({ pl, L, on, busy, err, open, bodies, onCheck, onBody, onApply, onCancel }: SealedProps) {
  const dlg = useRef<HTMLDialogElement>(null);
  const sealed = pl.state === "sealed", c = pl.counts || { actions: {}, units: {} }, t = tally(pl), items = pl.items || [];
  const table = Object.keys(c.units || {}).length ? <UnitTable caption="자료군별 개수" cols={MIG_ACTIONS} label={MIG_ACT} units={c.units} total={c.actions} /> : null;
  const errBox = <div className={css.err} id="mig-err" role="alert" aria-atomic="true">{err ? <MigErr e={err} items={items} /> : null}</div>;
  const cancel = <button type="button" className="secondary" disabled={busy} onClick={onCancel}>이 plan 취소</button>;
  const head = (
    <><div className="eyebrow">이관 plan</div><h2 className="title">{pl.source_instance} <StateChip st={pl.state} /></h2>
      <dl className="kv"><dt>plan</dt><dd><code>{pl.plan_id}</code></dd><dt>항목</dt><dd>{pl.item_count}개</dd><dt>올린 시각</dt><dd>{mdhm(pl.created_at)}</dd>
        {pl.state === "staged" || sealed ? <><dt>만료</dt><dd>{mdhm(pl.expires_at)}</dd></> : <><dt>닫은 시각</dt><dd>{mdhm(pl.closed_at)}</dd></>}
        {pl.plan_hash ? <><dt>plan_hash</dt><dd><code>{pl.plan_hash}</code></dd></> : null}</dl></>
  );
  if (pl.state === "staged") return <>{head}<p className="fnote">PC 업로더가 아직 다 올리지 않았어요(seal 전). 다 올리면 여기서 항목을 확인해요.</p>{errBox}<div className="frow">{cancel}</div></>;
  if (!sealed) return <>{head}<p className="fnote">{pl.state === "expired" ? "보관 기간이 지나 닫힌 plan이에요." : "취소한 plan이에요."} 올린 본문은 지웠어요. 다시 하려면 PC에서 다시 올려 주세요.</p>{errBox}{table}</>;
  const go = () => { dlg.current?.close?.(); onApply(); };
  return (
    <>
      {head}{table}
      <p className="hint">항목을 열어 본문을 확인하세요. 기준은 하나씩 체크해야 반영돼요 — 체크 안 한 기준은 반영하지 않아요. 중복 의심·충돌·거절 항목은 반영하지 않아요.</p>
      <section className="sec"><h2 className="sh">항목 <span className="speclabel">{`${items.length}개${t.checks ? ` · 기준 체크 ${t.checks - t.unchecked} / ${t.checks}` : ""}`}</span></h2>
        <ul className="rows">{items.map(x => <MigItem key={x.seq} x={x} sealed on={on} busy={busy} open={open.has(x.seq)} body={bodies[x.seq]} onCheck={onCheck} onBody={onBody} />)}</ul></section>
      {errBox}
      {on ? <>
        <div className={`frow ${css.acts}`}><button type="button" className="primary" disabled={busy} onClick={() => dlg.current?.showModal?.()}>반영</button>{cancel}
          {L ? <span className="tech">오늘 남은 이관 한도 {left(L)}행</span> : null}</div>
        <dialog ref={dlg} className={css.dlg} aria-labelledby="mig-dlg-title"><div className="dh"><b id="mig-dlg-title">이 plan을 반영할까요?</b></div><div className="db">
          <ul className={css.sum}>
            <li>새로 넣을 항목 <b>{t.insert}</b>개</li>
            <li>이미 있어 그대로 둘 항목 <b>{t.noop}</b>개</li>
            <li>체크 안 한 기준 <b>{t.unchecked}</b>개 — 반영하지 않아요</li>
            <li>중복 의심 <b>{t.warn}</b> · 충돌 <b>{t.conflict}</b> · 거절 <b>{t.reject}</b>개 — 반영하지 않아요</li>
            {L ? <li>오늘 남은 이관 한도 <b>{left(L)}</b>행</li> : null}</ul>
          <p className="hint">전부 반영하거나, 하나라도 실패하면 아무것도 반영하지 않아요. 반영한 뒤엔 이 화면에서 되돌릴 수 없어요.</p>
          <div className="frow"><button type="button" className="primary" onClick={go}>반영</button><button type="button" className="secondary" onClick={() => dlg.current?.close?.()}>닫기</button></div></div></dialog>
      </> : <><p className="fnote">{OFF.plan}</p><div className={`frow ${css.acts}`}>{cancel}</div></>}
    </>
  );
}
