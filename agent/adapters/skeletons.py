"""골격 어댑터 — 의미 규칙만 담는다. 실제 필드를 샘플로 확정하기 전에는 켤 수 없다(기본 비활성).

남은 골격은 kakao 하나다. feed·reactions·mail 은 collected.py 로 구현했다(2026-11-12). 서버로 가는 범위(S1):
수집 글은 URL·제목 줄·메타·AI 요약과 분석까지, 원문 본문 전체는 PC 원문 저장소에만.
변환 버전도 계약 TRANSFORMS 에 등록하지 않았다 — 켜도 계약 검증에서 막힌다.
공통 규칙(r3 T4):
- 파일 경로·행 번호만으로 영구 이벤트 ID 를 만들지 않는다.
- 제공자 이벤트 ID 가 있으면 PC 대응표에서 재사용, 없으면 중복 기준 확정 뒤 난수 ID 1회 발급.
- 판별할 수 없는 중복은 격리하고 집계하지 않는다.
- 명시적 행동 날짜가 없으면 occurred_on=None. 시간대를 모르면 KST 로 임의 변환하지 않는다.
- 활동 수집에 모델을 쓰지 않는다.
"""
from __future__ import annotations

from .base import Adapter, AdapterNotActive, TransmissionBlocked


class _Skeleton(Adapter):
    RULES: dict = {}

    def check_config(self, section: dict) -> None:
        if section.get("enabled"):
            raise AdapterNotActive(self.name + " adapter is a skeleton; fields not confirmed")

    def collect(self, section: dict):
        raise AdapterNotActive(self.name + " adapter is a skeleton; fields not confirmed")


class KakaoAdapter(_Skeleton):
    name = "kakao"
    transform_version = "board-kakao/1"
    RULES = {
        "pc_only": "대화·방 이름·참여자 실명·원문",
        "to_server": "확인된 사용자 발송·답장 등 명시 이벤트 → send/reply",
        "forbidden": "타인 메시지 수·대화 요약을 활동으로 변환 금지",
        "now": "카톡 글은 feed 어댑터의 채널 kakao 로 들어온다. 보낸·답한 행동을 담은 입력 파일이 생길 때까지 꺼 둔다",
    }


class LinkedInMovesAdapter(Adapter):
    """LinkedIn 이직 정보 — 서버 전송 분기 자체 차단(결정 16)."""
    name = "linkedin_moves"

    def check_config(self, section: dict) -> None:
        raise TransmissionBlocked(self.name)

    def collect(self, section: dict):
        raise TransmissionBlocked(self.name)


SKELETONS = {c.name: c for c in (KakaoAdapter,)}
