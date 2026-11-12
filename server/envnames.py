"""CRM_ 접두 env 읽기 헬퍼 — env("PUBLIC_URL") = CRM_PUBLIC_URL.

없으면 default. 빈 문자열은 그대로 돌려준다(os.environ.get 과 같다).
매번 os.environ 을 읽는다 — 시험이 실행 중에 값을 바꾼다.
"""

import os

PREFIX = "CRM_"


def env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(PREFIX + name, default)


# board 이전·연결 장치 스위치(구현계획 §2-10·§2-11 D5) — 코드 기본값 꺼짐.
# 2026-11-12 관리자 프로필: 켜고 끄기는 관리자 화면의 조직 기능 설정(features.py)으로 옮겼다. 이 env 는 ① 첫 시작 때 조직 설정 초기값
# ② 비상 끄기("1"·빈 값 = 조직 설정을 따름, 그 밖의 값 = 꺼짐)로만 남는다. 판정은 features.feature_on 하나다.
SWITCHES = ("IMPORTS_ENABLED",                       # /api/imports 수신 전체
            "ACTIVITY_IMPORTS_ENABLED",              # 활동 즉시 적재
            "UNATTENDED_SUMMARY_IMPORTS_ENABLED",    # 무인(execution=unattended) AI 요약 접수 — 약관 확인 전 꺼 둔다
            "INBOX_APPROVALS_ENABLED",               # 승인 대기 승인(제외·만료는 스위치와 무관)
            "BOARD_MIGRATION_ENABLED",               # board 이전 CLI 적용
            "CONVERSE_ENABLED", "ROUTINE_ENABLED",   # PR ②-a 작업 전달 — 대화(+원문 던지기)·루틴 작업. 읽기 자료(READING)는 ②-d 에서
            "TRASH_ENABLED",                         # 휴지통 PR-1 — 새 [삭제]·휴지통 화면·MCP 휴지통 쓰기. 꺼져도 일반 이용 차단·원천 차단·물리 정리는 돈다
            "MIGRATION_MCP_ENABLED",                 # 이관 MCP(가안 X) — 대화 이관 op 8개(읽기 포함). 기존 BOARD_MIGRATION_ENABLED·allowlist 위에 겹친다
            "WEBCHAT_ENABLED")                       # 웹 「대화」(구독 AI 채팅, 2026-11-04) — 꺼짐 = /api/chat/*·장치 WS·SSE 전부 503 SWITCH-OFF, 화면 숨김


def switch_on(name: str) -> bool:
    """SWITCHES 의 하나가 조직 단위로 켜졌나 — features.org_on 위임(사용자 프로필은 보지 않는다. 사용자 경로는 features.feature_on).
    모르는 이름은 ValueError(오타로 늘 꺼지는 것을 막는다)."""
    if name not in SWITCHES:
        raise ValueError(name)
    import features
    return features.org_on(features.BY_ENV[name].key)
