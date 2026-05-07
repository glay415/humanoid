"""턴 유형 정의 — 대화/DMN/정비 + 우선순위."""

from enum import IntEnum


class TurnType(IntEnum):
    """턴 유형. 값이 작을수록 우선순위 높음."""
    CONVERSATION = 1   # 최우선: 사용자 메시지 → 응답
    DMN = 2            # 중간: 유휴 시 DMN 사이클 1회
    MAINTENANCE = 3    # 낮음: 저수준만 작동 (감쇠, 마커 업데이트)
