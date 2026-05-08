"""트리거 레지스트리 — 조건부 이벤트 발동 + 우선순위 해소.

spec v12 §1.2 의 4단계 우선순위 해소 규칙 (audit ε4):

  1. EXTERNAL (외부) → 대화 턴. 진행 중인 DMN/정비 턴 즉시 중단.
  2. INTERNAL / RELATIONSHIP (내부 / 관계) → 동일 우선순위.
     ``IntEnum`` 값이 둘 다 2 이고 Python ``sorted`` 는 stable 이므로
     같은 슬롯 내에서 등록 순서가 보존된다.
  3. TEMPORAL (시간) → 대화/DMN 이 없을 때만.
  4. 같은 유형 내 복수 트리거는 등록 순서대로 직렬 처리.

규칙 4 는 ``check_all`` 의 sort key 가 ``t.category`` 단일 값이므로 stable
sort 에 의해 자동 보장된다.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Callable


class TriggerCategory(IntEnum):
    """트리거 우선순위. 값이 작을수록 우선.

    spec §1.2 4단계 해소 규칙:
      EXTERNAL (1) < INTERNAL (2) == RELATIONSHIP (2) < TEMPORAL (3).

    INTERNAL 과 RELATIONSHIP 의 값이 일부러 동일하다 — spec §1.2 "관계
    트리거 → 내부 트리거와 동일 우선순위". 같은 슬롯 내 정렬은 stable
    sort 에 의해 등록 순서로 결정된다.
    """
    EXTERNAL = 1     # 메시지 도착, 패턴 매칭
    INTERNAL = 2     # 드라이브 결핍, 기분 극단, 메타 자원, 반추
    RELATIONSHIP = 2 # 내부와 동일 우선순위 (의도적)
    TEMPORAL = 3     # 공백 임계값, 시간대 변화, 정비 주기


@dataclass
class Trigger:
    name: str
    category: TriggerCategory
    condition: Callable[..., bool]
    action: str  # 발동 대상 (턴 유형 or 이벤트)
    enabled: bool = True


class TriggerRegistry:
    """트리거 등록/발동/충돌 해소.

    spec §1.2 의 4단계 우선순위 규칙은 ``check_all`` 의 stable sort 로
    표현된다 — sort key 는 ``t.category`` (IntEnum) 단일. 같은 카테고리
    내에서는 ``self._triggers`` 의 등록 순서가 그대로 유지된다.
    """

    def __init__(self):
        self._triggers: list[Trigger] = []

    def register(self, trigger: Trigger) -> None:
        self._triggers.append(trigger)

    def check_all(self, context: dict) -> list[Trigger]:
        """현재 컨텍스트에서 발동 조건을 만족하는 트리거 목록.

        반환 순서는 spec §1.2 의 4단계 해소 규칙을 따른다:
        EXTERNAL → INTERNAL/RELATIONSHIP → TEMPORAL.
        같은 카테고리 내 복수 트리거는 등록 순서 (Python stable sort).
        """
        fired = []
        for t in self._triggers:
            if t.enabled and t.condition(context):
                fired.append(t)
        return sorted(fired, key=lambda t: t.category)
