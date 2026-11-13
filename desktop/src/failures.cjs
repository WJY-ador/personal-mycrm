'use strict';
// Why an app action failed, as the person reads it (spec 2026-11-13 §1.4): locked (another task), disconnected,
// login needed, server refused (code), unknown (code). The kind and a short code only — never an error's own text,
// which can carry server or sidecar content. desktop.log keeps the stage and kind; main maps codes to the report.
const KINDS = Object.freeze(['ok', 'busy', 'disconnected', 'login', 'rejected', 'unknown']);
const CODE = /^[A-Za-z0-9][A-Za-z0-9_-]{0,39}$/;
const HALTS = new Set(['auth', 'config', 'account', 'policy', 'forbidden', 'summary']);
const safe = code => (typeof code === 'string' && CODE.test(code) ? code : null);

// An error thrown inside an app action (connector.ConnectError, a lock refusal, a sidecar failure).
function classify(e) {
  const m = typeof e?.message === 'string' ? e.message : '';
  if (m === 'busy' || m === 'closing') return {kind: 'busy', code: null};
  if (m === 'login') return {kind: 'login', code: null};
  if (m === 'revoked' || m === 'not-connected') return {kind: 'disconnected', code: null};
  if (m === 'limit') return {kind: 'rejected', code: 'DEVICE-LIMIT'};
  if (m === 'name') return {kind: 'rejected', code: 'NAME-REQUIRED'};
  if (m === 'failed') return {kind: 'rejected', code: safe(e.code) || 'FAILED'};
  if (m === 'command-timeout' || m === 'agent-unavailable') return {kind: 'unknown', code: m};
  return {kind: 'unknown', code: 'error'};
}
// The run-once result: exit 0 ok, 3 a halt (its word from the fixed --resume hint), anything else unknown.
function syncOutcome({code, detail} = {}) {
  if (code === 0) return {kind: 'ok', code: null};
  if (code === 3) {
    const word = /--resume (\w+)/.exec(typeof detail === 'string' ? detail : '')?.[1];
    return {kind: 'rejected', code: HALTS.has(word) ? 'halt-' + word : 'halt'};
  }
  return {kind: 'unknown', code: Number.isInteger(code) ? 'exit-' + (code < 0 ? 'signal' : code) : 'exit'};
}
const TEXT = {
  ok: '완료했어요.',
  busy: '다른 작업이 진행 중이에요. 잠시 뒤 다시 시도해 주세요.',
  disconnected: '이 PC 연결이 끊겼어요. 대화에서 이 PC를 다시 연결해 달라고 말해 주세요.',
  login: '로그인이 필요해요. 대시보드에서 다시 로그인해 주세요.',
  rejected: '서버가 요청을 거절했어요',
  unknown: '알 수 없는 이유로 완료하지 못했어요',
};
// Fixed text for a notification; the code is appended for rejected and unknown.
function message({kind, code} = {}) {
  const k = KINDS.includes(kind) ? kind : 'unknown';
  const c = safe(code);
  return (k === 'rejected' || k === 'unknown') ? `${TEXT[k]}(코드 ${c || '없음'}).` : TEXT[k];
}
module.exports = Object.freeze({classify, syncOutcome, message, KINDS});
