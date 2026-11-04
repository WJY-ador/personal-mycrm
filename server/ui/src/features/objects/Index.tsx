// 자료 종류 색인(옛 renderObjects 목록) — 표준 자물쇠(코어 + 표준 정의) · 내 탭 · 커스텀. 카드 = 그 화면으로 이동, 「문의」 카드 = 껍데기 문의 대화창(data-open)
import type { KeyboardEvent, ReactNode } from "react";
import { meCount, qTabId, recTabId, userTabs } from "./model";
import type { P } from "./props";
import { Lock } from "../../shared/Glyph";
import { originChip } from "../../shared/origin";
import type { AppState } from "../../shared/state";
import css from "./Objects.module.css";

type Card = { label: string; api?: string; href: string; n: string | number; oc?: string };

function CardView({ S, c }: { S: AppState; c: Card }) {
  const go = () => { if (c.href) location.hash = c.href; };
  const key = (e: KeyboardEvent) => { if (c.href && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); go(); } };
  const chip = c.oc ? originChip(S, c.oc) : null;
  return (
    <article className="asset-card" tabIndex={0} role="button" {...(c.href ? { onClick: go, onKeyDown: key } : { "data-open": "mine" })}>
      <div className="top">{chip ? <span className={`chip ${chip[0]}`}>{chip[1]}</span> : null}</div><h3>{c.label}</h3>
      <div className="meta">{c.api ? <span className="tech">{c.api}</span> : null}<span>{c.n}{c.href ? "" : " · 내 문의 열기"}</span></div>
    </article>
  );
}

function Group({ S, title, cards, empty }: { S: AppState; title: ReactNode; cards: Card[]; empty: string }) {
  return (
    <section className={css.grp}><h3>{title}<span className="count">{cards.length}</span></h3>
      {cards.length ? <div className={css.grid}>{cards.map((c, i) => <CardView key={i} S={S} c={c} />)}</div> : <div className="empty">{empty}</div>}</section>
  );
}

export function Index({ S, msg }: P) {
  const cnt = S.source_counts || { by_source: {}, unconfirmed: 0 };
  const recTotal = Object.values(cnt.by_source || {}).reduce((s, n) => s + n, 0) + (cnt.unconfirmed || 0);
  const desk = !!document.getElementById("ui-desk");   // 문의 대화창 자리 = 서버가 사용자 응답에만 둔다(관리자 = 없음)
  const core: Card[] = [
    { label: "나", href: "#_me", n: "1" },
    { label: "질문", href: `#${qTabId(S)}`, n: (S.questions || []).length },
    { label: "내 글", href: `#${recTabId(S)}`, n: recTotal || (S.journal || []).length },
    { label: "검토할 판단", href: "#structure/cand/pending", n: (S.candidates || []).filter(c => c.status === "pending").length },
    { label: "출처", href: "#_obj/source", n: meCount(S, "sources") },
    { label: "사람", href: "#_obj/person", n: meCount(S, "people") },
    { label: "읽고 든 생각", href: "#_obj/reflection", n: meCount(S, "reflections") },
    { label: "활동", href: "#_obj/activity", n: S.activity ? `최근 30일 ${S.activity.total}` : "—" },
    ...(desk ? [{ label: "문의", href: "", n: "—" }] : []),
  ];
  const st = Array.isArray(S.structure?.objects) ? S.structure.objects : [];
  const nItems = (id: string) => (S.items || []).filter(it => it.object_id === id).length;
  const def = (o: (typeof st)[number], oc = ""): Card => ({ label: o.label, href: `#structure/${o.id}`, n: `항목 ${nItems(o.id)}`, oc });
  const tabs = userTabs(S);
  return (
    <div className="paper">{msg}<h2 className="title">자료 종류</h2>
      <Group S={S} title={<>표준 <Lock label="표준 정의 보호" /></>} cards={[...core, ...st.filter(o => o.origin === "standard").map(o => def(o))]} empty="" />
      {tabs.length ? <Group S={S} title="내 탭" cards={tabs.map(t => ({ label: t.label, api: t.view === "record" ? "글 탭" : "질문 탭", href: `#${t.id}`, n: "열기" }))} empty="" /> : null}
      <Group S={S} title="커스텀" cards={st.filter(o => o.origin !== "standard").map(o => def(o, o.origin))} empty="아직 내가 만든 자료 종류가 없어요." />
    </div>
  );
}
