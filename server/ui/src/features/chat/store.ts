// 대화 서랍 상태·흐름(옛 app.html 대화 절 CHAT·chat* 를 그대로 옮김 — 화면 없는 순수 TS, 시험이 함수 단위로 돌린다).
// 버튼 = 보내기·확정·닫기 3개. 바뀌는 것은 기본 포함(끄기 = 예외 제외), 자동 확정 없음. 정리 글을 고치면 즉시 [확정]을 잠그고, 정리 글 칸을 벗어날 때
// 재정리 작업 1개를 접수한다(키 입력마다 아님). 최신 작업(want)의 결과를 그린 뒤에만 [확정]이 켜진다 — 늦게 온 이전 결과·고친 뒤 도착한 결과는 버린다.
// 이어 받기 = 서버 S.stack_session(확정 전·만료 전 최신 세션 1) — 새로 고침 복원 · 두 탭이 같은 세션을 본다. 브라우저 저장소에는 아무것도 쓰지 않는다.
// 장치 상태 = 서버 S.devices_status 판정 그대로(state·last_seen_at 만 읽는다, 모르는 값 = 현행).
import { mdhm } from "../../shared/date";
import type { AppState } from "../../shared/state";
import { chatApi, type ChatApi, type Res } from "./chatApi";
import { CHAT_DONE, CHAT_ERR, CHAT_MAX, CHAT_NODEV, CHAT_WAIT, EDITED, NEWER, STALE, UNIT_JOIN, cp } from "./text";
import type { Change, Preview } from "./types";

const sleep = (ms: number) => new Promise(r => setTimeout(r, ms));
export const off = (p: Preview) => new Set(p.excluded || []);
export const changes = (p: Preview) => p.changes || [];
export const included = (p: Preview) => { const o = off(p); return changes(p).filter(c => !o.has(c.cid)); };
export const blocking = (p: Preview) => { const o = off(p); return (p.blocked || []).filter(b => !b.cid || !o.has(b.cid)); };
export const isGuess = (c: Change) => c.inferred === true || c.ref_kind === "inferred";   // 서버 표시 꼴 inferred(bool) — 「추정」 칩
export const label = (c: Change) => c.summary || c.label || c.cid;
const openBlock = (p: Preview) => p.blocked_open === true || blocking(p).length > 0;   // 서버 blocked_open 우선(없으면 화면 계산)
const errText = (r: { code: string; msg: string }) => CHAT_ERR[r.code] || r.msg || "보내지 못했어요. 다시 해 보세요.";
const key = (p: Preview | null) => (p ? `${p.id}:${p.preview_version}` : "");
function uuid() {
  if (crypto.randomUUID) return crypto.randomUUID();
  const b = crypto.getRandomValues(new Uint8Array(16)); b[6] = (b[6] & 15) | 64; b[8] = (b[8] & 63) | 128;
  const h = [...b].map(x => x.toString(16).padStart(2, "0")).join("");
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
}

export class ChatStore {
  api: ChatApi = { ...chatApi };
  S: AppState | null = null;
  reload: () => Promise<unknown> = async () => {};
  booted = false; open = false; sid = ""; kind = ""; jid = ""; want = ""; rv = ""; gen = 0; exp = ""; preview: Preview | null = null; ready = false;
  dirty = false; busy = ""; line = ""; bad = false; reqId = ""; reqFor = ""; turns: string[] = []; drawn: string | null = ""; polling = ""; known: Record<string, string> = {};
  // 화면 칸(옛 DOM 값) — 입력 글 · 원문으로 저장 · 그린 확인 카드 · 고친 정리 글 · 막힘 답 · 끄는 중인 변경
  input = ""; verbatim = false; card: Preview | null = null; edits: Record<string, string> = {}; answers: Record<number, string> = {}; unchecked = new Set<string>();
  private v = 0;
  private subs = new Set<() => void>();
  subscribe = (f: () => void) => { this.subs.add(f); return () => { this.subs.delete(f); }; };
  version = () => this.v;
  emit() { this.v++; this.subs.forEach(f => f()); }

  on() { return !!this.S?.switches?.converse; }
  dev() { const d = this.S?.devices_status; return d && ["none", "recent", "offline"].includes(d.state) ? d : null; }
  noDev() { const d = this.dev(); return !!d && d.state === "none"; }
  offline() { const d = this.dev(); return !!d && d.state === "offline"; }
  seen(d: { last_seen_at: string | null }) { return d.last_seen_at ? `마지막 연결 ${mdhm(d.last_seen_at)}` : ""; }
  devText() {
    const d = this.dev();
    if (!d || d.state === "none") return "";
    return d.state === "recent" ? "최근 연결" : ["PC 오프라인", this.seen(d)].filter(Boolean).join(", ");
  }
  // 받기를 기다리는 작업 — 오프라인이면 PC 를 기다린다고 알린다(할 일·만료는 서랍 안내 CHAT_OFFLINE). 보낸 글은 queued 로 남아 PC 가 오면 이어서 정리된다
  queuedLine() {
    const d = this.dev();
    if (d && d.state === "offline") return `PC를 기다리고 있어요${d.last_seen_at ? `(${this.seen(d)})` : ""}. PC가 연결되면 이어서 정리해요.`;
    return "PC 가 받기를 기다리고 있어요… PC 가 켜져 있어야 정리돼요.";
  }
  curSid() { return this.sid || (this.S?.stack_session ? String(this.S.stack_session.id || "") : ""); }   // 이어 받을 세션(첫 그리기 땐 아직 sid 전)
  ctxText() {
    return [this.devText(), this.sid ? `${this.kind === "verbatim" ? "원문으로 저장, " : ""}임시 보관${this.exp ? `, ${mdhm(this.exp)}까지` : ""}` : ""].filter(Boolean).join(", ");
  }
  canConfirm() { return !!(this.preview && this.ready && !this.dirty && !this.busy && !openBlock(this.preview)); }
  canToggle() { return !!(this.preview && this.ready && !this.dirty && !this.busy); }
  canSend() { return !this.noDev() && !this.busy && !!this.input.trim() && cp(this.input) <= CHAT_MAX; }

  setLine(text: string, bad = false) { this.line = text || ""; this.bad = !!bad; this.emit(); }
  reset() {
    Object.assign(this, { sid: "", kind: "", jid: "", want: "", rv: "", gen: 0, exp: "", preview: null, ready: false, dirty: false, busy: "",
      reqId: "", reqFor: "", turns: [], drawn: null, known: {}, verbatim: false });   // drawn null = 카드 칸을 다시 그린다(비운다)
  }
  // 그리기 — 확인 카드는 미리보기(id·판)가 바뀔 때만 다시 그린다(재정리를 기다리는 동안 고친 글이 그대로 남는다)
  draw() {
    const k = key(this.preview);
    if (k !== this.drawn && !this.dirty) {
      this.card = this.preview; this.drawn = k; this.unchecked = new Set(); this.answers = {};
      this.edits = Object.fromEntries((this.preview?.units || []).map(u => [u.uid, u.text]));
    }
    this.emit();
  }
  // 껍데기가 새 상태를 줄 때마다(옛 chatSync) — 스위치·첫 복원·열림 상태
  sync(S: AppState, reload: () => Promise<unknown>) {
    this.S = S; this.reload = reload;
    const on = this.on();   // 장치 없음이어도 확정만 남은 세션은 이어 받는다(새 작업 접수만 막는다)
    if (!on) this.open = false;
    if (on && !this.booted) {
      this.booted = true;
      const sid = S.stack_session?.id;   // 확인을 기다리는 대화가 있으면 서랍을 열어 이어 받는다
      if (sid) { this.sid = String(sid); this.open = true; void this.restore(this.sid); }
    }
    this.draw();
  }
  toggle(open = !this.open) { this.open = open; this.draw(); }

  // 미리보기 그리기 — 최신 작업(want)의 결과만. 고치는 중이면 버린다. rv = 그 미리보기를 낸 작업의 result.result_version
  show(p: Preview, jid: string, rv?: string) {
    if (jid !== this.want || this.dirty) return false;
    this.preview = p; this.jid = jid; this.ready = p.latest !== false;   // latest=false = 늦게 온 옛 결과(확정 불가)
    if (rv && String(rv) !== this.rv) this.known = {};   // 변경 ID 는 결과 하나 안에서만 같은 뜻 — 결과가 바뀌면 본 이름을 잊는다
    if (rv) this.rv = String(rv);
    for (const c of changes(p)) this.known[c.cid] = label(c);   // 뺀 것 이름 — 빼기 전 판에서 본 변경
    if (p.edit_generation != null) this.gen = Math.max(this.gen, Number(p.edit_generation) || 0);
    this.line = p.latest === false ? "이 결과는 최신이 아니에요. 최신 결과를 기다려 주세요." : openBlock(p) ? "정해 주세요 칸에 답하면 다시 정리해요." : "확인하고 [확정]을 눌러 주세요.";
    this.bad = p.latest === false;
    this.draw();
    return true;
  }
  async wait(jid: string, say?: string) {
    this.want = jid; this.ready = false;
    if (this.polling === jid) return;   // 같은 작업을 이미 기다리는 중 — 롱폴을 겹치지 않는다(사용자당 동시 2)
    this.polling = jid;
    try { await this.poll(jid, say); } finally { if (this.polling === jid) this.polling = ""; }
  }
  async poll(jid: string, say?: string) {
    this.setLine(this.offline() ? this.queuedLine() : say || "정리하고 있어요…");   // 오프라인 = 첫 롱폴(최대 30초) 전에도 진행 중으로 보이지 않게
    for (;;) {
      const t0 = Date.now();
      const res = await this.api.poll(jid);
      if (this.want !== jid || !res) return;   // 더 새 작업이 있다 — 이 응답은 버린다
      if (!res.ok) {
        if (res.code === "RATE-LIMIT" || res.code === "OFFLINE") { this.setLine(res.code === "OFFLINE" ? "연결을 다시 시도하고 있어요…" : "잠시 뒤 다시 확인할게요…"); await sleep(5000); continue; }
        this.setLine(errText(res), true); return;
      }
      const j = res.j;
      if (j.expires_at) this.exp = j.expires_at;
      if (CHAT_WAIT.includes(j.status)) {
        this.setLine(j.status === "queued" ? this.queuedLine() : "정리하고 있어요…");
        if (Date.now() - t0 < 1000) await sleep(1000);   // 롱폴이 바로 돌아와도 초당 1번 넘게 묻지 않는다
        continue;
      }
      if (j.status === "result_ready" && j.preview) {
        if (!this.show(j.preview, jid, j.result?.result_version) && this.want === jid) this.setLine(EDITED);
        return;
      }
      if (j.status === "expired") this.reset();
      this.line = CHAT_DONE[j.status] || "정리하지 못했어요. 다시 보내 주세요."; this.bad = true;
      this.draw();
      return;
    }
  }
  // 작업 접수 공통 — 새 턴·재정리 모두 같은 세션(서버·PC 가 세션 안에서 한 번에 하나씩 실행한다)
  async submit(body: Record<string, unknown>, say?: string) {
    if (this.noDev()) { this.dirty = false; this.setLine(CHAT_NODEV, true); return false; }   // 장치 없음 = 작업 접수 0(새 턴·재정리·막힘 답)
    this.busy = "send"; this.ready = false;
    this.setLine("보내는 중…");
    const res = await this.api.send(body);
    this.busy = "";
    if (!res) return false;
    if (!res.ok) {
      if ((res.code === "NOT-FOUND" || res.status === 410) && this.sid) { this.reset(); this.line = "이 대화는 끝났어요(확정했거나 만료). 다시 보내면 새로 시작해요."; this.bad = true; this.draw(); return false; }
      if (res.code === "CONFIRM-STALE" && this.sid) {   // 옛 편집 세대 — 다른 탭이 먼저 다시 정리했다
        this.setLine("다른 탭에서 먼저 다시 정리했어요. 최신 결과를 불러올게요.", true);
        if (await this.restore(this.sid) === "shown") this.setLine(`${NEWER} 확인하고 다시 고치거나 [확정]을 눌러 주세요.`, true);
        return false;
      }
      this.setLine(errText(res), true); return false;
    }
    if (!this.sid) { this.sid = res.j.session_id; this.kind = String(body.input_kind || "converse"); }
    this.draw();
    void this.wait(res.j.id, say);
    return true;
  }
  async send() {
    const text = this.input;
    if (this.busy || this.dirty || !text.trim() || cp(text) > CHAT_MAX) return;
    const body: Record<string, unknown> = { kind: "converse", text };
    if (this.sid) body.session_id = this.sid;
    else body.input_kind = this.verbatim ? "verbatim" : "converse";
    if (await this.submit(body)) { this.turns.push(text); this.input = ""; this.draw(); }
  }
  // 정리 글 칸 — 고치면 즉시 잠금(요청 0), 칸을 벗어날 때 재정리(blur)
  edit(uid: string, text: string) {
    this.edits = { ...this.edits, [uid]: text };
    if (!this.dirty) { this.dirty = true; this.line = EDITED; this.bad = false; }
    this.emit();
  }
  leave() { if (this.dirty && !this.busy) void this.restack(); }
  edited() { return (this.card?.units || []).map(u => this.edits[u.uid] ?? u.text).join(UNIT_JOIN); }
  // 재정리 — 원 결과 참조 · 편집 세대 · 고친 글 · 뺀 변경 · 막힘 답을 구조로 보낸다(text = edited_text). 입력 종류는 첫 입력 그대로
  async restack(extra?: Record<string, unknown>) {
    const text = this.edited();
    if (!text.trim()) { this.setLine("정리 글이 비었어요. 내용을 적어 주세요.", true); return; }
    if (cp(text) > CHAT_MAX) { this.setLine(CHAT_ERR["PAYLOAD-LIMIT"], true); return; }
    const o = this.preview ? [...off(this.preview)] : [];
    const rs = { parent_result_version: this.rv, edit_generation: this.gen + 1, edited_text: text, ...(o.length ? { excluded_cids: o } : {}), ...(extra || {}) };
    this.dirty = false;
    if (await this.submit({ kind: "converse", session_id: this.sid, text, restack: rs }, "다시 정리하고 있어요…")) this.gen = rs.edit_generation;   // 접수됐을 때만 세대를 올린다
  }
  // 막힌 질문의 답 = 재정리(answers). 적어 둔 답을 모두 함께 보낸다
  answer() {
    if (this.busy || this.dirty || !this.card) return;
    const answers = blocking(this.card).map((b, i) => ({ cid: b.cid || null, text: (this.answers[i] || "").trim() })).filter(a => a.text);
    if (answers.length) void this.restack({ answers });
  }
  setAnswer(i: number, text: string) { this.answers = { ...this.answers, [i]: text }; this.emit(); }   // i = 카드의 「정해 주세요」 순번
  // 예외 제외 — 끈 변경(과 거기 기대는 변경·같은 문단)을 서버가 빼고 새 미리보기를 준다. 기계적으로 못 빼면 재정리
  async exclude(cid: string) {
    const p = this.preview;
    if (!p || !this.canToggle()) { this.recheck(cid); return; }
    this.unchecked.add(cid);
    this.busy = "exclude"; this.setLine("빼는 중…");
    const res: Res<{ preview?: Preview } & Partial<Preview>> = await this.api.exclude(p.id, [cid]);
    this.busy = "";
    if (!res) return;
    if (res.ok) { this.show((res.j.preview || res.j) as Preview, this.want, this.rv); return; }
    if (res.code === "PREVIEW-NEEDS-RESTACK") { if (this.noDev()) this.recheck(cid); void this.restack({ excluded_cids: [...off(p), cid] }); return; }   // 장치 없음 = 재정리 못 함 — 다시 켜 둔다
    if (res.code === "CONFIRM-STALE" && this.sid) { this.setLine(STALE, true); void this.restore(this.sid); return; }
    this.recheck(cid);
    this.setLine(errText(res), true);
  }
  private recheck(cid: string) { this.unchecked.delete(cid); this.emit(); }
  async confirm() {
    if (!this.canConfirm()) return;
    const p = this.preview!, k = key(p);
    if (this.reqFor !== k) { this.reqId = uuid(); this.reqFor = k; }   // 같은 미리보기 재시도 = 같은 요청 ID(응답 유실 대비)
    this.busy = "confirm"; this.setLine("저장하는 중…");
    const res = await this.api.confirm(this.jid, { request_id: this.reqId, preview_id: p.id, preview_version: p.preview_version, preview_sha: p.preview_sha });
    this.busy = "";
    if (!res) return;
    if (res.ok) {
      const n = included(p).length;
      this.reset();
      this.line = `저장했어요. 변경 ${n}건`; this.bad = false;
      this.draw();
      await this.reload();   // 「나」 통계·목록 갱신(상태)
      return;
    }
    if (res.code === "CONFIRM-STALE") {
      this.ready = false;
      this.setLine(STALE, true);
      if (this.sid && await this.restore(this.sid) === "shown") this.setLine(`${NEWER} 확인하고 다시 [확정]을 눌러 주세요.`, true);
      return;
    }
    if (res.code === "CONFIRM-CONFLICT" || res.code === "JOB-DEFS") { this.setLine("정리한 뒤 대상이나 구조가 바뀌었어요. 다시 정리할게요.", true); void this.restack(); return; }
    if (res.code === "CONFIRM-REQUEST-MISMATCH") { this.reqFor = ""; this.setLine("확인 내용이 바뀌었어요. 다시 [확정]을 눌러 주세요.", true); return; }
    if (res.status === 410 || res.code === "JOB-GONE") { this.reset(); this.line = CHAT_DONE.expired; this.bad = true; this.draw(); return; }
    if (res.code === "IMPORT-QUOTA") { this.setLine(`오늘 남길 수 있는 글 수를 넘었어요${this.kind === "verbatim" ? "(원문으로 저장하면 원문과 정리 2편)" : ""}. 아무것도 저장하지 않았어요. 내일 다시 확정해 주세요.`, true); return; }
    if (res.code === "OFFLINE") { this.setLine("연결이 끊겼어요. 다시 [확정]을 누르면 같은 요청으로 다시 보내요(두 번 저장되지 않아요).", true); return; }
    this.setLine(errText(res), true);
  }
  // 새로 고침·두 탭 — 세션의 최신 작업·미리보기를 서버에서 다시 받는다(대화 턴 표시는 이 화면 메모리에만 있어 복원하지 않는다)
  // 반환 = "shown"(최신 미리보기를 그림) · "wait"(작업 기다림) · "end"(세션 끝 — 기억 지움) · "fail"
  async restore(sid: string): Promise<string> {
    const res = await this.api.session(sid);
    if (!res || sid !== this.sid) return "fail";
    if (!res.ok) {
      if (res.code === "NOT-FOUND" || res.code === "JOB-GONE") { this.reset(); this.line = "대화 세션이 끝났어요. 다시 보내면 새로 시작해요."; this.bad = true; this.draw(); return "end"; }
      this.setLine("대화를 불러오지 못했어요. 새로 고침해 주세요.", true);
      return "fail";
    }
    const s = res.j;
    if (s.confirmed) { this.reset(); this.line = "이 대화는 이미 확정했어요(다른 탭일 수 있어요)."; this.bad = true; this.draw(); await this.reload(); return "end"; }
    if (s.expires_at && Date.parse(s.expires_at) <= Date.now()) { this.reset(); this.line = CHAT_DONE.expired; this.bad = true; this.draw(); return "end"; }
    this.kind = s.input_kind || this.kind || "converse"; this.exp = s.expires_at || this.exp;
    this.gen = Math.max(this.gen, Number(s.edit_generation) || 0);
    const lj = s.latest_job || { id: "", status: "" };
    this.dirty = false; this.preview = null; this.ready = false;
    if (lj.id && CHAT_WAIT.includes(lj.status)) {   // 오프라인 대기 문구는 poll 이 첫 롱폴 전에 고른다(최근 연결 = 기존 문구)
      this.preview = s.preview || null; this.draw();
      void this.wait(lj.id); return "wait";
    }
    this.want = lj.id || "";
    if (s.preview && lj.status === "result_ready") {   // 원 결과 버전은 작업 응답에만 있다 — 그 작업을 한 번 읽어 미리보기와 같이 그린다
      const r = await this.api.poll(lj.id);
      if (sid !== this.sid || this.want !== lj.id) return "fail";
      if (r && r.ok && r.j.status === "result_ready" && r.j.preview) { this.show(r.j.preview, lj.id, r.j.result?.result_version); return "shown"; }
    }
    if (lj.status && CHAT_DONE[lj.status]) { this.line = CHAT_DONE[lj.status]; this.bad = true; }
    this.draw();
    return "fail";
  }
}

export const chat = new ChatStore();   // 서랍 하나(껍데기가 상태마다 다시 띄워도 대화는 이어진다)
