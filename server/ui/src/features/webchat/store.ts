// 웹 「대화」 상태 — 화면 없는 순수 TS. 열면 세션 하나(서버가 활성 1을 돌려줌) → SSE 하나로 재생·실시간. 입력 = POST(client_turn_id 멱등).
// 턴 = 사용자 글 + 답(delta 합) + 도구 호출 목록 + 끝 상태. 같은 SSE id 는 두 번 그리지 않는다. 브라우저 저장소에는 아무것도 쓰지 않는다.
import { apiErr } from "../../shared/api";
import { webchatApi, type Es, type WebchatApi } from "./api";
import type { Approval } from "./api";
import { REPLACED, TEXT_MAX, TRIMMED, endText, errText } from "./text";

export type Tool = { name: string; input?: unknown; ok?: boolean; summary?: string };
export type Turn = { id: string; user: string; answer: string; tools: Tool[]; end: "" | "done" | "error"; endNote: string; last: number };
type Ev = { turn_id: string; seq?: number; data?: Record<string, unknown>; text?: string };

const cid = () => (crypto.randomUUID ? crypto.randomUUID() : `t${Date.now().toString(36)}${Math.random().toString(36).slice(2, 10)}`);
const str = (v: unknown) => (typeof v === "string" ? v : "");

export class WebchatStore {
  api: WebchatApi = { ...webchatApi };
  open = false; sid = ""; device = ""; connected = false; turns: Turn[] = []; input = ""; line = ""; bad = false; sending = false;
  provider = ""; model: string | null = null; bindingVersion = 0; readOnly = false;
  selectorOpen = false; loading = false; capabilities: import("./api").Capabilities = { devices: [] };
  approvals: Approval[] = []; approvalsLoading = false; approvalsError = ""; approvalAction = ""; approvalLine = ""; approvalBad = false;
  approvalResult: { id: string; result: unknown } | null = null;
  replaced = false; trimmed = "";   // replaced = 다른 탭이 이 대화를 열어 이 탭의 SSE 가 끝남(다시 붙지 않는다) · trimmed = 재생에서 생략된 앞부분 안내
  private es: Es | null = null;
  private approvalsRequest = false;
  private approvalsRequestSid = "";
  private approvalsRequestSeq = 0;
  private approvalsPromise: Promise<void> | null = null;
  private v = 0;
  private subs = new Set<() => void>();
  subscribe = (f: () => void) => { this.subs.add(f); return () => { this.subs.delete(f); }; };
  version = () => this.v;
  emit() { this.v++; this.subs.forEach(f => f()); }

  running() { const t = this.turns[this.turns.length - 1]; return !!t && !t.end; }
  canSend() { const n = [...this.input].length; return !!this.sid && !this.readOnly && !this.selectorOpen && !this.replaced && this.connected && !this.sending && !this.running() && !!this.input.trim() && n <= TEXT_MAX; }
  say(text: string, bad = false) { this.line = text; this.bad = bad; this.emit(); }

  async toggle(on = !this.open) {
    this.open = on;
    this.emit();
    if (on && !this.sid) await this.start();
    else if (on && this.replaced) { this.line = ""; this.listen(); }   // 다른 탭에서 열렸던 대화 — 이 탭에서 다시 열면 이 탭이 이어 받는다
  }

  async start() {
    if (this.loading) return;
    this.loading = true; this.line = ""; this.bad = false; this.emit();
    try {
      const { sessions } = await this.api.sessions();
      const active = sessions.find(x => x.status === "active");
      if (active) {
        const s = active.binding_version === 2 ? await this.api.resume(active.session_id) : active;
        this.attach(s, active.binding_version !== 2);
      } else await this.loadCapabilities();
    } catch (e) { this.say(errText(apiErr(e)), true); }
    finally { this.loading = false; this.emit(); }
  }

  private attach(s: Awaited<ReturnType<WebchatApi["resume"]>>, readOnly = false) {
    this.sid = s.session_id; this.device = s.device_id; this.connected = !!s.connected;
    this.provider = s.provider || ""; this.model = s.model; this.bindingVersion = s.binding_version; this.readOnly = readOnly;
    this.selectorOpen = false; this.turns = []; this.line = ""; this.approvals = []; this.listen();
    this.approvalsLoading = false; this.approvalsError = ""; this.approvalAction = ""; this.approvalLine = ""; this.approvalBad = false; this.approvalResult = null;
    this.approvalsRequest = false; this.approvalsRequestSid = ""; this.approvalsRequestSeq++; this.approvalsPromise = null;
    void this.loadApprovals();
  }

  async loadApprovals(forceAfterCurrent = false): Promise<void> {
    const sid = this.sid;
    if (!sid) return;
    if (this.approvalsRequest && this.approvalsRequestSid === sid) {
      if (!forceAfterCurrent) return this.approvalsPromise || undefined;
      await this.approvalsPromise;
      if (this.sid === sid) return this.loadApprovals();
      return;
    }
    this.approvalsRequest = true; this.approvalsRequestSid = sid; this.approvalsLoading = true; this.approvalsError = ""; this.emit();
    const requestSeq = ++this.approvalsRequestSeq;
    const request = (async () => {
      try {
        const { approvals } = await this.api.approvals(sid);
        if (this.sid === sid) {
          this.approvals = Array.isArray(approvals) ? approvals : [];
          if (this.approvalResult && this.approvals.some(a => a.id === this.approvalResult?.id && a.status === "confirmed")) this.approvalResult = null;
        }
      } catch (e) {
        if (this.sid === sid) { this.approvals = []; this.approvalsError = approvalLoadError(apiErr(e)); }
      } finally {
        if (this.approvalsRequestSeq === requestSeq) { this.approvalsRequest = false; this.approvalsRequestSid = ""; this.approvalsPromise = null; }
        if (this.sid === sid) { this.approvalsLoading = false; this.emit(); }
      }
    })();
    this.approvalsPromise = request;
    await request;
  }

  async actOnApproval(id: string, action: "confirm" | "cancel") {
    if (!this.sid || this.approvalAction || !this.approvals.some(a => a.id === id && a.status === "pending")) return;
    const sid = this.sid;
    this.approvalAction = id; this.approvalLine = ""; this.approvalBad = false; this.approvalResult = null; this.emit();
    try {
      if (action === "confirm") {
        const response = await this.api.confirmApproval(sid, id);
        if (this.sid !== sid) return;
        this.approvalResult = { id, result: response.result ?? null };
      } else {
        await this.api.cancelApproval(sid, id);
        if (this.sid !== sid) return;
      }
      this.approvalLine = action === "confirm" ? "요청을 확인했어요." : "요청을 취소했어요.";
      await this.loadApprovals(true);
    } catch (e) {
      if (this.sid !== sid) return;
      this.approvalLine = approvalError(apiErr(e)); this.approvalBad = true;
      await this.loadApprovals(true);
    } finally { if (this.sid === sid) { this.approvalAction = ""; this.emit(); } }
  }

  async loadCapabilities() {
    try { this.capabilities = await this.api.capabilities(); this.selectorOpen = true; }
    catch (e) { this.say(errText(apiErr(e)), true); }
    this.emit();
  }

  async newConversation() {
    if (this.running() || this.sending || this.input.trim()) {
      this.say(this.running() || this.sending ? "답이 끝난 뒤 새 대화를 시작할 수 있어요." : "미전송 글을 보내거나 지운 뒤 새 대화를 시작하세요.", true);
      return;
    }
    await this.loadCapabilities();
  }

  async createSession(device: string, provider: string, model: string | null) {
    if (this.running() || this.sending || this.input.trim()) {
      this.say(this.running() || this.sending ? "답이 끝난 뒤 새 대화를 시작할 수 있어요." : "미전송 글을 보내거나 지운 뒤 새 대화를 시작하세요.", true);
      return;
    }
    const deviceInfo = this.capabilities.devices.find(d => d.device_id === device && d.connected);
    const option = deviceInfo?.capabilities.find(c => c.provider === provider);
    if (!option || !option.models.includes(model)) return;
    this.loading = true; this.line = ""; this.bad = false; this.emit();
    try {
      const id = cid();
      const s = await this.api.create(device, provider, model, id);
      this.attach(s);
    } catch (e) { this.say(errText(apiErr(e)), true); }
    finally { this.loading = false; this.emit(); }
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
    if (this.readOnly) return;
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

function approvalError(e: { code: string; msg: string; status?: number }) {
  if (e.msg) return e.msg;
  if (e.status === 409) return "요청이 만료되었거나 변경되어 처리하지 못했어요. 목록을 새로 확인하세요.";
  if (e.status === 403 || e.status === 404) return "이 요청에 접근할 수 없어요. 목록을 새로 확인하세요.";
  return e.code === "OFFLINE" ? "승인 요청을 불러오지 못했어요. 연결을 확인하세요." : "승인 요청을 처리하지 못했어요. 다시 확인하세요.";
}

function approvalLoadError(e: { code: string; msg: string; status?: number }) {
  if (e.msg) return e.msg;
  return e.code === "OFFLINE" ? "승인 요청을 불러오지 못했어요. 연결을 확인하세요." : "확인 요청을 불러오지 못했어요. 다시 시도하세요.";
}

export const webchat = new WebchatStore();
