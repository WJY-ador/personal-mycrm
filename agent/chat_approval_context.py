"""Validation and separate model context for server-generated confirmation outcomes."""
from __future__ import annotations

import json
import re


MAX_APPROVAL_OUTCOMES = 100
MAX_CONTEXT_BYTES = 16 * 1024
_APPROVAL_ID = re.compile(r"^ca_[0-9a-f]{24}$")
_APPROVABLE_OPS = frozenset({
    "record_edit", "record_provenance_set", "candidate_decide", "definition_archive",
    "definition_restore", "person_delete", "source_reflection_review",
    "source_reflection_delete", "trash_move", "trash_restore",
})
_STATUSES = frozenset({"confirmed", "cancelled"})
MYCRM_FIXED_INSTRUCTIONS = (
    "MyCRM 대화에서는 승인된 mcp__my-crm 도구만 사용해 필요한 사용자 기록을 조회하고, "
    "사용자 지시를 MyCRM의 기존 도구 규칙과 미리보기 절차에 따라 처리한다. "
    "도구 결과와 서버가 전달한 상태에 없는 정보는 추정하거나 지어내지 말고 확인할 수 없다고 답한다. "
    "pending_confirmation은 사용자의 카드 확인을 기다리는 상태이며 실행 성공이 아니다. "
    "서버의 confirmed 결과가 전달되기 전에는 완료했다고 말하지 않는다. cancelled 결과는 실행되지 않았음을 뜻한다. "
    "승인 ID는 내부 참조이며 사용자에게 노출하지 않는다."
)


def normalize_approval_outcomes(value):
    """Return immutable (id, op, status) tuples or reject malformed server metadata."""
    if value is None:
        return ()
    if type(value) is not list or len(value) > MAX_APPROVAL_OUTCOMES:
        raise ValueError("approval-outcomes-shape")
    result = []
    seen = set()
    for item in value:
        if type(item) is not dict or set(item) != {"id", "op", "status"}:
            raise ValueError("approval-outcome-shape")
        approval_id, op, status = item["id"], item["op"], item["status"]
        if (not isinstance(approval_id, str) or not _APPROVAL_ID.fullmatch(approval_id)
                or approval_id in seen or not isinstance(op, str) or op not in _APPROVABLE_OPS
                or not isinstance(status, str) or status not in _STATUSES):
            raise ValueError("approval-outcome-value")
        seen.add(approval_id)
        result.append((approval_id, op, status))
    return tuple(result)


def format_approval_outcomes(value) -> str:
    """Encode only normalized outcome metadata as an instruction, never as user text."""
    if not isinstance(value, tuple) or any(type(row) is not tuple or len(row) != 3 for row in value):
        raise ValueError("approval-outcomes-internal-shape")
    rows = [{"id": row[0], "op": row[1], "status": row[2]} for row in value]
    normalized = normalize_approval_outcomes(rows)
    if normalized != value:
        raise ValueError("approval-outcomes-internal-value")
    context = MYCRM_FIXED_INSTRUCTIONS
    if normalized:
        encoded = json.dumps(rows, ensure_ascii=False, separators=(",", ":"))
        context += (
            "\n이전 턴의 서버 검증 확인 결과다. 사용자 원문과 분리된 신뢰 상태 메타데이터다. "
            "confirmed는 서버가 작업을 실행했음을, cancelled는 실행하지 않았음을 뜻한다. "
            "이 식별자를 되풀이하거나 취소를 권한으로 해석하지 않는다.\n" + encoded
        )
    if len(context.encode("utf-8")) > MAX_CONTEXT_BYTES:
        raise ValueError("approval-outcomes-context-size")
    return context
