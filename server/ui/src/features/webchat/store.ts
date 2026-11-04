// 웹 「대화」 상태 — 화면 없는 순수 TS. 열면 세션 하나(서버가 활성 1을 돌려줌) → SSE 하나로 재생·실시간. 입력 = POST(client_turn_id 멱등).
// 턴 = 사용자 글 + 답(delta 합) + 도구 호출 목록 + 끝 상태. 같은 SSE id 는 두 번 그리지 않는다. 브라우저 저장소에는 아무것도 쓰지 않는다.
import { apiErr } from "../../shared/api";
import { webchatApi, type Es, type WebchatApi } from "./api";
import { REPLACED, TEXT_MAX, TRIMMED, endText, errText } from "./text";

export type Tool = { name: string; input?: unknown; ok?: boolean; summary?: string };
export type Turn = { id: string; user: string; answer: string; tools: Tool[]; end: "" | "done" | "error"; endNote: string; last: number };
type Ev = { turn_id: string; seq?: number; data?: Record<string, unknown>; text?: string };

const cid = () => (crypto.randomUUID ? crypto.randomUUID() : `t${Date.now().toString(36)}${Math.random().toString(36).slice(2, 10)}`);
const str = (v: unknown) => (typeof v === "string" ? v : "");

export class WebchatStore {
  api: WebchatApi = { ...webchatApi };
  open = false; sid = ""; device = ""; connected = false; turns: Turn[] = []; input = ""; line = ""; bad = false; sending = false;
  replaced = false; trimmed = "";   // replaced = 다른 탭이 이 대화를 열어 이 탭의 SSE 가 끝남(다시 붙지 않는다) · trimmed = 재생에서 생략된 앞부분 안내
  private es: Es | null = null;
  private v = 0;
  private subs = new Set<() => void>();
  subscribe = (f: () => void) => { this.subs.add(f); return () => { this.subs.delete(f); }; };
  version = () => this.v;
  emit() { this.v++; this.subs.forEach(f => f()); }

  running() { const t = this.turns[this.turns.length - 1]; return !!t && !t.end; }
  canSend() { const n = [...this.input].length; return !!this.sid && !this.replaced && this.connected && !this.sending && !this.running() && !!this.input.trim() && n <= TEXT_MAX; }
  say(text: string, bad = false) { this.line = text; this.bad = bad; this.emit(); }

  async toggle(on = !this.open) {
    this.open = on;
    this.emit();
    if (on && !this.sid) await this.start();
    else if (on && this.replaced) { this.line = ""; this.listen(); }   // 다른 탭에서 열렸던 대화 — 이 탭에서 다시 열면 이 탭이 이어 받는다
  }

  async start() {
    try {
      const s = await this.api.open();
      this.sid = s.session_id; this.device = s.device_id; this.connected = !!s.connected; this.turns = []; this.line = "";
      this.listen();
    } catch (e) { this.say(errText(apiErr(e)), true); }
    this.emit();
  }

  listen() {
    this.es?.close();
    const es = this.es = this.api.stream(this.sid);
    this.replaced = false; this.trimmed = ""; this.turns = [];   // 재생이 처음부터(또는 최근 N턴) 다시 그린다
    const on = (t: string, f: (d: Ev & Record<string, unknown>) => void) =>
      es.addEventListener(t, (m: MessageEvent) => { try { f(JSON.parse(String(m.data))); } catch { return; } this.emit(); });
    on("pc", d => { if (!d.device_id || d.device_id === this.device) this.connected = d.connected === true; });   // 이 대화의 PC 만
    on("replaced", () => { es.close(); if (this.es === es) this.es = null; this.replaced = true; this.say(REPLACED); });
    on("trimmed", () => { this.trimmed = TRIMMED; });
    on("turn", d => {
      if (!this.turns.some(t => t.id === d.turn_id)) this.turns.push({ id: d.turn_id, user: str(d.text), answer: "", tools: [], end: "", endNote: "", last: 0 });
    });
    for (const k of ["delta", "tool_call", "tool_result", "done", "error"]) on(k, d => this.event(k, d));
  }

  event(kind: string, d: Ev) {
    const t = this.turns.find(x => x.id === d.turn_id);
    const seq = Number(d.seq || 0);
    if (!t || seq <= t.last) return;   // 재생·실시간 겹침 — 한 번만
    t.last = seq;
    const x = d.data || {};
    if (kind === "delta") t.answer += str(x.text);
    else if (kind === "tool_call") t.tools.push({ name: str(x.name) || "도구", input: x.input });
    else if (kind === "tool_result") {
      const open = [...t.tools].reverse().find(o => o.ok === undefined && (!x.name || o.name === x.name));
      if (open) { open.ok = x.ok === true; open.summary = str(x.summary); } else t.tools.push({ name: str(x.name) || "도구", ok: x.ok === true, summary: str(x.summary) });
    } else if (kind === "done") t.end = "done";
    else { t.end = "error"; t.endNote = endText(str(x.code)); }
  }

  async send() {
    if (!this.canSend()) return;
    const text = this.input;
    this.sending = true; this.line = ""; this.emit();
    try {
      await this.api.turn(this.sid, text, cid());
      this.input = "";
    } catch (e) {
      const err = apiErr(e);
      if (err.code === "DEVICE-GONE" || err.code === "SESSION-CLOSED") this.sid = "";
      this.say(errText(err), true);
    } finally { this.sending = false; this.emit(); }
  }

  async stop() {
    try { await this.api.stop(this.sid); } catch (e) { this.say(errText(apiErr(e)), true); }
  }

  close() { this.es?.close(); this.es = null; }
}

export const webchat = new WebchatStore();
