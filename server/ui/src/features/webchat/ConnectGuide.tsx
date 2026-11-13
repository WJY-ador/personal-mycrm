// 연결 안내(대화 하나로 J-F1, 2026-11-13 앱 하나) — 쓸 수 있는 AI가 없으면 한 줄 문구 대신 2단계: 1 PC 앱 받기와 로그인(PC 는 자동 연결), 2 AI 연결.
// 멈춘 단계는 서버가 아는 상태(capabilities.setup)로만 정한다: none = PC 없음, offline = PC 는 있으나 PC 앱 꺼짐,
// no_provider = PC 앱은 켜졌으나 쓸 AI 없음, no_link = 새 앱인데 연결된 AI 없음. 앱 창 안이면 2단계에 AI 연결 버튼(AiLinks)이 바로 뜬다.
import type { Setup } from "./api";
import { AiLinks } from "./AiLinks";
import type { WebchatStore } from "./store";
import { GUIDE_DOWNLOAD, GUIDE_NOTE, GUIDE_OFFLINE, GUIDE_RECHECK, GUIDE_STATE, GUIDE_STEPS, GUIDE_TITLE } from "./text";
import css from "./Webchat.module.css";

type StepState = "done" | "now" | "todo";
const STATES: Record<Exclude<Setup, "ready">, StepState[]> = {
  none: ["now", "todo"], offline: ["now", "todo"], no_provider: ["done", "now"], no_link: ["done", "now"],
};

export function ConnectGuide({ s }: { s: WebchatStore }) {
  const setup = s.capabilities.setup && s.capabilities.setup !== "ready" ? s.capabilities.setup : "no_link";
  const states = STATES[setup] || STATES.none;
  return (
    <section className={css.guide} aria-label={GUIDE_TITLE} data-setup={setup}>
      <h4>{GUIDE_TITLE}</h4>
      <p>{GUIDE_NOTE}</p>
      <ol>
        {GUIDE_STEPS.map((step, i) => (
          <li key={step.title} className={css.step} data-state={states[i]} aria-current={states[i] === "now" ? "step" : undefined}>
            <h5>{step.title} <span className={css.stepState}>{GUIDE_STATE[states[i]]}</span></h5>
            <p>{i === 0 && setup === "offline" ? GUIDE_OFFLINE : step.text}</p>
            {states[i] === "now" && <div className={css.stepActs}>
              {i === 0 && setup === "none" && <a className="btn primary" href="/download" target="_blank" rel="noopener">{GUIDE_DOWNLOAD}</a>}
              {i === 1 && <AiLinks s={s} />}
              <button type="button" className="tertiary" disabled={s.capsLoading} onClick={() => void s.loadCapabilities()}>{GUIDE_RECHECK}</button></div>}
          </li>
        ))}
      </ol>
    </section>
  );
}
