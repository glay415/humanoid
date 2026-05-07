"""경험 마커 — 접근/회피 태그 수치 관리.

Damasio의 as-if loop 구현. 패턴(의미적 요약)은 고수준 LLM이 생성하고,
저수준은 수치(valence, strength)만 관리.
"""

from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class Marker:
    """단일 경험 마커."""
    pattern_id: str           # 고수준이 부여한 패턴 식별자
    valence: float            # reward - threat (접근 +, 회피 -)
    strength: float           # max(reward, threat) at formation
    age: int = 0              # 형성 후 경과 턴 수

    def decay(self, rate: float) -> None:
        """정비 시 자동 감쇠. 강도가 높을수록 감쇠 저항."""
        resistance = min(self.strength, 0.9)  # 극강 기억은 감쇠 저항
        effective_rate = rate * (1.0 - resistance)
        self.strength = max(0.0, self.strength - effective_rate)
        self.age += 1

    def reinforce(self, new_valence: float, new_strength: float,
                  weight: float = 0.3) -> None:
        """동일 패턴 재경험 시 가중 평균 갱신."""
        self.valence = weight * new_valence + (1.0 - weight) * self.valence
        self.strength = weight * new_strength + (1.0 - weight) * self.strength


class MarkerRegistry:
    """경험 마커 컬렉션. 형성/감쇠/조회."""

    def __init__(
        self,
        formation_threshold: float = 0.7,
        decay_rate: float = 0.01,
    ):
        self.markers: dict[str, Marker] = {}
        self.formation_threshold = formation_threshold
        self.decay_rate = decay_rate

    def maybe_form(
        self,
        pattern_id: str,
        reward: float,
        threat: float,
    ) -> Marker | None:
        """reward 또는 threat > 임계값이면 마커 형성/갱신."""
        if reward <= self.formation_threshold and threat <= self.formation_threshold:
            return None

        valence = reward - threat
        strength = max(reward, threat)

        if pattern_id in self.markers:
            self.markers[pattern_id].reinforce(valence, strength)
        else:
            self.markers[pattern_id] = Marker(
                pattern_id=pattern_id,
                valence=valence,
                strength=strength,
            )
        return self.markers[pattern_id]

    def decay_all(self) -> list[str]:
        """정비 사이클: 전체 감쇠. 강도 0 이하인 마커 ID 반환 후 제거."""
        expired = []
        for pid, marker in list(self.markers.items()):
            marker.decay(self.decay_rate)
            if marker.strength <= 0.0:
                expired.append(pid)
                del self.markers[pid]
        return expired

    def get(self, pattern_id: str) -> Marker | None:
        return self.markers.get(pattern_id)

    def all_markers(self) -> list[Marker]:
        return list(self.markers.values())
