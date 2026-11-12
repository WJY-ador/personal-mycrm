"""입력 어댑터 — 수집기 산출물을 「관측 행동」으로 바꾼다. 모델을 쓰지 않는다.

활성 구현: likes · feed · reactions · mail(수집 글과 활동, 기본 꺼짐 — 설정에 입력 경로를 적어 켠다).
골격(의미 규칙만, 켤 수 없음): kakao.
전송 분기 차단: linkedin_moves(LinkedIn 이직 정보는 PC 에만).
"""
from __future__ import annotations

from .base import AdapterError, AdapterNotActive, CollectedPost, Observation, Quarantine, TransmissionBlocked
from .collected import FeedAdapter, MailAdapter, ReactionsAdapter
from .likes import LikesAdapter
from .skeletons import SKELETONS, LinkedInMovesAdapter

ACTIVE = {"likes": LikesAdapter, "feed": FeedAdapter, "reactions": ReactionsAdapter, "mail": MailAdapter}
BLOCKED = {"linkedin_moves": LinkedInMovesAdapter}


def get(name: str):
    if name in BLOCKED:
        raise TransmissionBlocked(name)
    if name in ACTIVE:
        return ACTIVE[name]()
    if name in SKELETONS:
        return SKELETONS[name]()
    raise AdapterError("unknown adapter")


__all__ = ["AdapterError", "AdapterNotActive", "CollectedPost", "Observation", "Quarantine", "TransmissionBlocked",
           "LikesAdapter", "FeedAdapter", "ReactionsAdapter", "MailAdapter", "get", "ACTIVE", "BLOCKED", "SKELETONS"]
