"""경험 마커 — 접근/회피 태그 수치 관리.

Damasio의 as-if loop 구현. 패턴(의미적 요약)은 고수준 LLM이 생성하고,
저수준은 수치(valence, strength)만 관리.

spec §8.2 invariant
-------------------
경험 마커는 **고수준이 직접 지울 수 없다**. 마커는 오직 두 경로로 사라진다:
  1. ``decay_all()`` — strength 가 자연 감쇠로 0 이하가 되면 expired 처리.
  2. (없음) — 명시적 ``remove()`` API 자체가 존재하지 않는다.

따라서 ``MarkerRegistry`` 에는 의도적으로 ``remove`` / ``clear`` / ``pop``
함수가 없다. 누군가 우회로 ``registry.markers.pop(pid)`` 를 시도하면
``markers`` dict 의 raw API 가 통하긴 하지만, 정상 코드 경로에서는 호출
하지 않으며 lint / 코드 리뷰에서 반려된다.

만약 향후 ``remove`` 가 필요해지더라도 그것은 spec §8.2 위반이므로
``low_level.spec_invariants.SpecViolation`` 을 raise 하는 trap 으로만
구현해야 한다.
"""

from __future__ import annotations
from dataclasses import dataclass, field

from low_level.spec_invariants import SpecViolation


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
    """경험 마커 컬렉션. 형성/감쇠/조회.

    spec §8.2: ``remove`` 메서드가 없다 — 마커는 자연 감쇠로만 사라진다.
    """

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

    def load_all(self) -> list[dict]:
        """ADR-022 — DMN Activity 2 (case_promote) 가 ctx.marker_store.load_all
        시그니처로 마커들을 읽는다. storage.MarkerStore.load_all 과 동일 shape
        (list of dict with pattern_id / valence / strength / age) 로 반환해
        in-memory registry 가 영속 store 와 듀얼 backend 로 동작 가능.
        """
        return [
            {
                'pattern_id': m.pattern_id,
                'valence': float(m.valence),
                'strength': float(m.strength),
                'age': int(m.age),
            }
            for m in self.markers.values()
        ]

    def remove(self, pattern_id: str) -> None:
        """spec §8.2: 마커 직접 삭제는 spec 위반 — 항상 SpecViolation.

        decay_all() 의 자연 감쇠만이 제거 경로다. 이 trap 은 향후 누군가
        실수로 ``registry.remove(pid)`` 를 호출해 invariant 를 우회하지 못하게
        한다.
        """
        raise SpecViolation(
            f"spec §8.2 — markers cannot be directly removed. "
            f"only decay_all() (natural strength decay → 0) removes a marker. "
            f"attempted to remove '{pattern_id}'."
        )

    def clear(self) -> None:
        """spec §8.2: 일괄 삭제도 차단."""
        raise SpecViolation(
            "spec §8.2 — markers cannot be cleared en masse. "
            "use decay_all() repeatedly during maintenance instead."
        )
