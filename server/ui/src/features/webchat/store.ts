// 웹 「대화」 상태 — 화면 없는 순수 TS. 열면 활성 세션이 있으면 그것(SSE 하나로 재생과 실시간), 없으면 빈 새 대화.
// 새 대화는 첫 메시지를 보낼 때 고른 모델로 시작한다(세션에 공급자와 모델을 고정하는 서버 계약 그대로). Claude, Codex 는 PC 허용(grant)을 먼저 받는다:
//   요청(POST /api/chat/grants) → 대기(GET 상태 1.5초 간격) → 허용 = 같은 id 로 세션 생성 → 보내려던 글 보내기.
// 턴 = 사용자 글 + 답(delta 합) + 도구 호출 목록 + 끝 상태. 같은 SSE id 는 두 번 그리지 않는다.
// 브라우저 저장소에는 모델 선택(PC, 공급자, 모델 이름) 하나만 쓴다. 글과 대화 내용은 쓰지 않는다.
import { apiErr } from "../../shared/api";
import { webchatApi, type Capabilities, type Es, type Grant, type Message, type Session, type WebchatApi } from "./api";
import type { Approval } from "./api";
import { BUSY_NEW, PAST_END, REPLACED, TEXT_MAX, TRIMMED, endText, errText } from "./text";

export type Tool = { name: string; input?: unknown; ok?: boolean; summary?: string };
export type Turn = { id: string; user: string; answer: string; tools: Tool[]; end: "" | "done" | "error"; endNote: string; last: number };
export type Choice = { device: string; provider: string; model: string | null };
export type GrantNote = "" | "asking" | "none" | "open" | "approved" | "closed" | "expired" | "offline";
type Ev = { turn_id: string; seq?: number; data?: Record<string, unknown>; text?: string };

export const MODEL_KEY = "mycrm-webchat-model";
export const GRANT_PROVIDERS = ["claude", "codex"];   // server/webchat.py GRANT_PROVIDERS 와 같은 값 — fake 는 허용 없이 시작
export const GRANT_POLL_MS = 1500;
const cid = () => (crypto.randomUUID ? crypto.randomUUID() : `t${Date.now().toString(36)}${Math.random().toString(36).slice(2, 10)}`);
const str = (v: unknown) => (typeof v === "string" ? v : "");
export const choiceKey = (c: Choice) => `${c.device}|${c.provider}|${c.model ?? ""}`;
const same = (a: Choice | null, b: Choice | null) => !!a && !!b && choiceKey(a) === choiceKey(b);

export type Saved = { get(): string | null; set(v: string): void; drop(): void };
const local: Saved = {   // 막힌 저장소(사생활 모드 등) = 기억 없이 동작
  get() { try { return localStorage.getItem(MODEL_KEY); } catch { return null; } },
  set(v) { try { localStorage.setItem(MODEL_KEY, v); } catch { return; } },
  drop() { try { localStorage.removeItem(MODEL_KEY); } catch { return; } },
};

export class WebchatStore {
  api: WebchatApi = { ...webchatApi };
  saved: Saved = local;
  sleep = (ms: number) => new Promise<void>(r => setTimeout(r, ms));
  open = false; sid = ""; device = ""; connected = false; turns: Turn[] = []; input = ""; line = ""; bad = false; sending = false;
  provider = ""; model: string | null = null; bindingVersion = 0; readOnly = false;
  loading = false; capabilities: Capabilities = { devices: [] }; capsLoaded = false; capsLoading = false;
  choice: Choice | null = null; pickerOpen = false; pendingPick: Choice | null = null;
  grant: Grant | null = null; grantNote: GrantNote = ""; grantText = "";
  view: "chat" | "history" = "chat"; past: Session[] = []; pastLoading = false; pastError = "";
  approvals: Approval[] = []; approvalsLoading = false; approvalsError = ""; approvalAction = ""; approvalLine = ""; approvalBad = false;
  approvalResult: { id: string; result: unknown } | null = null;
  replaced = false; trimmed = "";   // replaced = 다른 탭이 이 대화를 열어 이 탭의 SSE 가 끝남(다시 붙지 않는다) · trimmed = 재생에서 생략된 앞부분 안내
  private es: Es | null = null;
  private grantSeq = 0;
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
  waiting() { return this.grantNote === "asking" || this.grantNote === "none" || this.grantNote === "open" || this.grantNote === "approved"; }
  canSend() {
    const n = [...this.input].length;
    if (this.readOnly || this.replaced || this.sending || this.running() || this.waiting() || !this.input.trim() || n > TEXT_MAX) return false;
    return this.sid ? this.connected : !!this.choice;
  }
  say(text: string, bad = false) { this.line = text; this.bad = bad; this.emit(); }

  // 고를 수 있는 (PC, 공급자, 모델) — 서버가 준 capabilities(연결된 PC 만) 순서 그대로
  choices(): Choice[] {
    return this.capabilities.devices.filter(d => d.connected).flatMap(d => d.capabilities.flatMap(c => c.models.map(m => ({ device: d.device_id, provider: c.provider, model: m }))));
  }
  // 고르기 버튼에 보일 것 — 진행 중 대화가 있으면 그 대화에 고정된 모델, 없으면 다음 새 대화에 쓸 선택
  shown(): Choice | null { return this.sid && this.provider ? { device: this.device, provider: this.provider, model: this.model } : this.choice; }

  async toggle(on = !this.open) {
    this.open = on;
    this.emit();
    if (on && !this.sid && !this.capsLoaded) await this.start();
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
      }
    } catch (e) { this.say(errText(apiErr(e)), true); }
    finally { this.loading = false; this.emit(); }
    await this.loadCapabilities();
  }

  // 지난번 선택 복원 — 목록에 없으면 버린다. 목록이 비었으면(PC 꺼짐 등) 기억은 지우지 않고 선택만 비운다
  async loadCapabilities() {
    if (this.capsLoading) return;
    this.capsLoading = true; this.emit();
    try {
      this.capabilities = await this.api.capabilities(); this.capsLoaded = true;
      const list = this.choices();
      const keep = this.choice && list.find(c => same(c, this.choice));
      const saved = this.saved.get();
      const fromSaved = saved ? list.find(c => choiceKey(c) === saved) : undefined;
      if (saved && !fromSaved && list.length) this.saved.drop();
      this.choice = keep || fromSaved || list[0] || null;
    } catch (e) { this.say(errText(apiErr(e)), true); }
    finally { this.capsLoading = false; this.emit(); }
  }

  togglePicker(on = !this.pickerOpen) {
    this.pickerOpen = on; this.pendingPick = null; this.emit();
    if (on) void this.loadCapabilities();   // 열 때마다 새로(PC 가 켜지고 꺼질 수 있다)
  }

  // 진행 중 대화(턴이 하나라도 있음) + 다른 모델 = 확인 뒤 새 대화. 그 밖 = 바로 다음 새 대화의 선택
  pick(c: Choice) {
    const bound = this.shown();
    if (this.sid && !this.readOnly && this.turns.length && !same(bound, c)) { this.pendingPick = c; this.emit(); return; }
    this.choose(c);
    if (this.sid && !this.readOnly && !same(bound, c)) this.detach();
    this.pickerOpen = false; this.emit();
  }

  confirmPick() {
    const c = this.pendingPick;
    if (!c) return;
    if (this.running() || this.sending) { this.pendingPick = null; this.say(BUSY_NEW, true); return; }
    this.choose(c); this.detach(); this.pickerOpen = false; this.pendingPick = null; this.emit();
  }

  private choose(c: Choice) { this.choice = c; this.saved.set(choiceKey(c)); }

  // 화면만 빈 새 대화로 — 서버의 활성 세션은 다음 세션이 만들어질 때 서버가 닫는다(session_new). 입력 칸의 글은 그대로 둔다
  private detach() {
    this.es?.close(); this.es = null;
    Object.assign(this, { sid: "", device: "", connected: false, provider: "", model: null, bindingVersion: 0, readOnly: false, turns: [], trimmed: "", replaced: false, line: "", bad: false });
    this.resetApprovals();
  }

  newChat() {
    if (this.running() || this.sending) { this.say(BUSY_NEW, true); return; }
    this.cancelGrant(); this.detach(); this.view = "chat"; this.emit();
  }

  private resetApprovals() {
    this.approvals = []; this.approvalsLoading = false; this.approvalsError = ""; this.approvalAction = ""; this.approvalLine = ""; this.approvalBad = false; this.approvalResult = null;
    this.approvalsRequest = false; this.approvalsRequestSid = ""; this.approvalsRequestSeq++; this.approvalsPromise = null;
  }

  private attach(s: Session, readOnly = false) {
    this.sid = s.session_id; this.device = s.device_id; this.connected = !!s.connected;
    this.provider = s.provider || ""; this.model = s.model; this.bindingVersion = s.binding_version; this.readOnly = readOnly;
    this.turns = []; this.line = ""; this.view = "chat"; this.listen();
    this.resetApprovals();
    void this.loadApprovals();
  }

  // ── 지난 대화(읽기 전용) — 목록 = GET /api/chat/sessions, 열기 = 활성이면 이어 받기, 끝난 대화면 messages ──
  async openHistory(on = this.view !== "history") {
    this.view = on ? "history" : "chat"; this.pickerOpen = false; this.emit();
    if (!on) return;
    this.pastLoading = true; this.pastError = ""; this.emit();
    try { this.past = (await this.api.sessions()).sessions; }
    catch (e) { this.past = []; this.pastError = errText(apiErr(e)); }
    finally { this.pastLoading = false; this.emit(); }
  }

  async openPast(s: Session) {
    if (this.running() || this.sending || this.waiting()) { this.say(BUSY_NEW, true); return; }
    if (s.status === "active" && s.binding_version === 2) {
      if (this.sid === s.session_id && !this.readOnly) { this.view = "chat"; this.emit(); return; }
      try { this.attach(await this.api.resume(s.session_id)); } catch (e) { this.say(errText(apiErr(e)), true); }
      this.emit(); return;
    }
    this.detach();
    Object.assign(this, { sid: s.session_id, device: s.device_id, provider: s.provider || "", model: s.model, bindingVersion: s.binding_version, readOnly: true, view: "chat" });
    this.emit();
    try {
      const { messages } = await this.api.messages(s.session_id);
      if (this.sid === s.session_id) this.turns = pastTurns(messages);
    } catch (e) { if (this.sid === s.session_id) this.say(errText(apiErr(e)), true); }
    this.emit();
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

  // ── 새 대화 시작(첫 메시지) — fake 는 바로, Claude 와 Codex 는 PC 허용 뒤 같은 id 로 ──
  private async begin(c: Choice) {
    if (!GRANT_PROVIDERS.includes(c.provider)) return this.create(c, cid());
    return this.requestGrant(c, cid());
  }

  async requestGrant(c: Choice, rid: string) {
    const seq = ++this.grantSeq;
    this.grantNote = "asking"; this.grantText = this.input; this.line = ""; this.bad = false; this.emit();
    try {
      this.grant = await this.api.grant(c.device, c.provider, c.model, rid);
    } catch (e) { if (seq === this.grantSeq) { this.grantNote = ""; this.say(errText(apiErr(e)), true); } return false; }
    while (seq === this.grantSeq) {
      const g = this.grant;
      if (!g) return false;
      if (g.state === "approved") break;
      if (g.state === "expired" || g.state === "consumed") { this.grantNote = "expired"; this.emit(); return false; }
      if (g.connected === false) { this.grantNote = "offline"; this.emit(); return false; }
      if (g.prompt === "closed") { this.grantNote = "closed"; this.emit(); return false; }
      this.grantNote = g.prompt === "open" ? "open" : "none"; this.emit();
      await this.sleep(GRANT_POLL_MS);
      if (seq !== this.grantSeq) return false;
      try { this.grant = await this.api.grantStatus(rid); }
      catch (e) { this.grantNote = ""; this.say(errText(apiErr(e)), true); return false; }
    }
    if (seq !== this.grantSeq) return false;
    this.grantNote = "approved"; this.emit();
    const made = await this.create(c, rid);
    if (seq === this.grantSeq) { this.grantNote = ""; this.grant = null; }
    this.emit();
    return made;
  }

  // 다시 요청 = 새 id 로 새 허용 요청(옛 요청은 5분 뒤 서버에서 만료). 같은 id 를 다시 쓰면 앞 창의 끝난 상태(closed)가 남아 바로 다시 끝난다
  async retryGrant() {
    const g = this.grant;
    if (!g || this.waiting()) return;
    if (await this.requestGrant({ device: g.device_id, provider: g.provider, model: g.model }, cid())) await this.send();
  }

  cancelGrant() { this.grantSeq++; this.grant = null; this.grantNote = ""; this.emit(); }

  private async create(c: Choice, id: string) {
    try {
      const s = await this.api.create(c.device, c.provider, c.model, id);
      this.attach(s);
      return true;
    } catch (e) { this.say(errText(apiErr(e)), true); return false; }
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
    if (!this.sid) {
      const c = this.choice;
      if (!c) return;
      this.sending = true;   // 첫 메시지 두 번 누름 = 세션 두 번 만들기 방지
      let made = false;
      try { made = await this.begin(c); } finally { this.sending = false; }
      if (!made || !this.sid || !this.canSend()) { this.emit(); return; }
    }
    const text = this.input;
    this.sending = true; this.line = ""; this.emit();
    try {
      await this.api.turn(this.sid, text, cid());
      this.input = "";
    } catch (e) {
      const err = apiErr(e);
      if (err.code === "DEVICE-GONE" || err.code === "SESSION-CLOSED") this.detach();
      this.say(errText(err), true);
    } finally { this.sending = false; this.emit(); }
  }

  async stop() {
    try { await this.api.stop(this.sid); } catch (e) { this.say(errText(apiErr(e)), true); }
  }

  close() { this.es?.close(); this.es = null; this.cancelGrant(); }
}

// 지난 대화 messages(턴마다 user, assistant 한 줄씩) → 턴. 끝난 상태는 turn_status 로
export function pastTurns(messages: Message[]): Turn[] {
  const out: Turn[] = [];
  for (const m of messages) {
    let t = out.find(x => x.id === m.turn_id);
    if (!t) {
      const st = m.turn_status;
      t = { id: m.turn_id, user: "", answer: "", tools: [], end: st === "done" ? "done" : "error", endNote: st === "done" ? "" : PAST_END[st] || PAST_END.failed, last: 0 };
      out.push(t);
    }
    if (m.role === "user") t.user = m.body; else t.answer = m.body;
  }
  return out;
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
