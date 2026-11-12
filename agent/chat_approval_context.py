"""Validation and separate model context for server-generated confirmation outcomes."""
from __future__ import annotations

import json
import re


MAX_APPROVAL_OUTCOMES = 100
MAX_CONTEXT_BYTES = 16 * 1024
MAX_CREATED_KEYS = 2
_APPROVAL_ID = re.compile(r"^ca_[0-9a-f]{24}$")
# Card-approvable ops: every decide op, purge (trash_purge) and write 14 (server/webchat.py CHAT_CARD_OPS,
# server/ui text.ts OP_NAME keep the same set; a server test compares the three).
_APPROVABLE_OPS = frozenset({
    "record_edit", "record_provenance_set", "candidate_decide", "definition_apply", "definition_archive",
    "definition_restore", "item_decide", "person_delete", "source_reflection_review",
    "source_reflection_delete", "inbox_decide", "trash_move", "trash_restore", "feedback_send",
    "migration_apply", "migration_cancel", "migration_revert", "migration_token_send", "pc_forget",
    "token_revoke", "trash_purge",
    "layout_set", "layout_reset", "display_name_set", "question_add", "profile_set",
    "record_add", "record_attach", "record_title_set", "candidates_propose", "definition_propose",
    "item_propose", "person_save", "source_create", "source_reflection_save",
})
# Only a confirmed write card may carry `created` ({key: id}, at most 2 keys). Values must match the
# server generators listed in server/webchat.py _CREATED_ID_RE: db.new_id = prefix_ + 11 urlsafe chars,
# object = od_ + 10 hex. Never text.
_CREATED_OPS = frozenset({
    "layout_set", "layout_reset", "display_name_set", "question_add", "profile_set",
    "record_add", "record_attach", "record_title_set", "candidates_propose", "definition_propose",
    "item_propose", "person_save", "source_create", "source_reflection_save",
})
_CREATED_KEYS = frozenset({"id", "source_id", "object_id", "proposal_id", "item_id"})
_CREATED_ID = re.compile(r"^(?:od_[0-9a-f]{10}|(?:q|r|s|p|sr|dp|i|ip)_[A-Za-z0-9_-]{11})$")
_STATUSES = frozenset({"confirmed", "cancelled"})
MYCRM_FIXED_INSTRUCTIONS = (
    "MyCRM 대화에서는 승인된 mcp__my-crm 도구만 사용해 필요한 사용자 기록을 조회하고, "
    "사용자 지시를 MyCRM의 기존 도구 규칙과 미리보기 절차에 따라 처리한다. "
    "도구 결과와 서버가 전달한 상태에 없는 정보는 추정하거나 지어내지 말고 확인할 수 없다고 답한다. "
    "pending_confirmation은 사용자의 카드 확인을 기다리는 상태이며 실행 성공이 아니다. "
    "서버의 confirmed 결과가 전달되기 전에는 완료했다고 말하지 않는다. cancelled 결과는 실행되지 않았음을 뜻한다. "
    "쓰기, 확정, 삭제(write, decide, purge)는 모두 사용자가 카드로 확인한 뒤에만 실행된다. "
    "되돌릴 수 없는 카드는 사용자가 두 번 확인한다. "
    "이어지는 쓰기는 한 턴에 잇지 말고, 다음 턴에 confirmed 결과의 created id로 한다. "
    "승인 ID는 내부 참조이며 사용자에게 노출하지 않는다. "
    "사용자가 이 대화를 남기라고 하면 record_add(text_process=structured, decision_owner=self)로 초안을 올린다. "
    "형식: 주제마다 제목 한 줄과 문단 하나, 사용자 1인칭, 결정 하나에 문단 하나, 어휘는 사용자 것만, AI 내부 추론은 쓰지 않는다, "
    "동기는 대화에 있는 것만 쓰고 없으면 \"동기: 대화에 없음\"."
)


def _normalize_created(op, status, value):
    """Return a non-empty sorted tuple of (key, id) pairs. The server omits `created` when empty."""
    if type(value) is not dict or not value:
        raise ValueError("approval-outcome-created")
    if status != "confirmed" or op not in _CREATED_OPS or len(value) > MAX_CREATED_KEYS:
        raise ValueError("approval-outcome-created")
    pairs = []
    for key, created_id in value.items():
        if (not isinstance(key, str) or key not in _CREATED_KEYS
                or not isinstance(created_id, str) or not _CREATED_ID.fullmatch(created_id)):
            raise ValueError("approval-outcome-created")
        pairs.append((key, created_id))
    return tuple(sorted(pairs))


def _rows(value):
    rows = []
    for row in value:
        item = {"id": row[0], "op": row[1], "status": row[2]}
        if len(row) == 4:
            item["created"] = dict(row[3])
        rows.append(item)
    return rows


def _context(rows) -> str:
    context = MYCRM_FIXED_INSTRUCTIONS
    if rows:
        encoded = json.dumps(rows, ensure_ascii=False, separators=(",", ":"))
        context += (
            "\n이전 턴의 서버 검증 확인 결과다. 사용자 원문과 분리된 신뢰 상태 메타데이터다. "
            "confirmed는 서버가 작업을 실행했음을, cancelled는 실행하지 않았음을 뜻한다. "
            "created는 확인된 쓰기가 만든 항목의 id이며 다음 쓰기에 이어 쓸 수 있다. "
            "이 식별자를 되풀이하거나 취소를 권한으로 해석하지 않는다.\n" + encoded
        )
    if len(context.encode("utf-8")) > MAX_CONTEXT_BYTES:
        raise ValueError("approval-outcomes-context-size")
    return context


def normalize_approval_outcomes(value):
    """Return immutable outcome tuples or reject malformed server metadata.

    Each row is (id, op, status) or, for a confirmed write card with ids, (id, op, status, created)
    where created is a sorted tuple of (key, id) pairs. The model context built from the rows must
    fit MAX_CONTEXT_BYTES, so an oversize list is rejected here, before a provider starts.
    """
    if value is None:
        return ()
    if type(value) is not list or len(value) > MAX_APPROVAL_OUTCOMES:
        raise ValueError("approval-outcomes-shape")
    result = []
    seen = set()
    for item in value:
        if type(item) is not dict or set(item) not in ({"id", "op", "status"}, {"id", "op", "status", "created"}):
            raise ValueError("approval-outcome-shape")
        approval_id, op, status = item["id"], item["op"], item["status"]
        if (not isinstance(approval_id, str) or not _APPROVAL_ID.fullmatch(approval_id)
                or approval_id in seen or not isinstance(op, str) or op not in _APPROVABLE_OPS
                or not isinstance(status, str) or status not in _STATUSES):
            raise ValueError("approval-outcome-value")
        seen.add(approval_id)
        if "created" in item:
            result.append((approval_id, op, status, _normalize_created(op, status, item["created"])))
        else:
            result.append((approval_id, op, status))
    result = tuple(result)
    _context(_rows(result))
    return result


def format_approval_outcomes(value) -> str:
    """Encode only normalized outcome metadata as an instruction, never as user text."""
    if (not isinstance(value, tuple)
            or any(type(row) is not tuple or len(row) not in (3, 4) for row in value)
            or any(len(row) == 4 and (type(row[3]) is not tuple or not row[3]
                                      or any(type(pair) is not tuple or len(pair) != 2 for pair in row[3]))
                   for row in value)):
        raise ValueError("approval-outcomes-internal-shape")
    rows = _rows(value)
    normalized = normalize_approval_outcomes(rows)
    if normalized != value:
        raise ValueError("approval-outcomes-internal-value")
    return _context(rows)
