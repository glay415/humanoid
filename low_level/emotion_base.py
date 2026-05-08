"""감정 기저 — raw 코어 어펙트 + 기분 (leaky integral).

저수준 전용. meta_resource 참조 없음 (계층 분리).
final_core_affect 보정은 interface/signal_rise.py가 담당.
"""

import numpy as np

from low_level.spec_invariants import (
    SpecViolation,
    _LL_TOKEN,
    _check_protected_setattr,
    assert_low_level,
)


# spec §8.1: 기분(``mood``) 은 의지로 바꿀 수 없다.
# spec §8.4: 코어 어펙트(``raw_core_affect``) 도 직접 선택할 수 없다.
# 직접 attribute 할당은 __setattr__ 로 caller 검증.

class EmotionBase:
    """raw_core_affect(valence, arousal) 계산 + mood leaky integral."""

    _PROTECTED_ATTRS = frozenset({'mood', 'raw_core_affect'})

    def __init__(
        self,
        mood_decay_eta: float = 0.05,
        negativity_weight: float = 0.6,
        drive_alpha: float = 0.1,
        drive_gamma: float = 0.05,
    ):
        # __setattr__ 우회 — init 단계.
        object.__setattr__(self, 'raw_core_affect', {'valence': 0.0, 'arousal': 0.0})
        object.__setattr__(self, 'mood', {'valence': 0.0, 'arousal': 0.0})
        self.eta = mood_decay_eta
        self.negativity_weight = negativity_weight
        self.drive_alpha = drive_alpha
        self.drive_gamma = drive_gamma

    def __setattr__(self, name: str, value) -> None:
        """spec §8.1, §8.4: ``mood`` / ``raw_core_affect`` 직접 할당 차단.

        허용 caller: low_level/, interface/, ui/backend/state_serializer.
        """
        if name in EmotionBase._PROTECTED_ATTRS:
            _check_protected_setattr(name, owner='emotion_base')
        object.__setattr__(self, name, value)

    def update_raw_core_affect(
        self,
        state: dict[str, float],
        max_drive_deficit: float = 0.0,
    ) -> dict[str, float]:
        """내부 상태 9개 + 드라이브 결핍 → raw 코어 어펙트."""
        positive = (state['reward'] + state['comfort'] + state['bonding']) / 3.0
        negative = state['stress'] * self.negativity_weight
        # Full-range linear mapping. positive ∈ [0,1], negative ∈ [0, nw],
        # 따라서 (positive - negative) ∈ [-nw, 1]. 분모 (1+nw) 로 정규화 후
        # [0,1] → [-1,+1] 로 늘려 양 끝까지 정보 손실 없이 매핑.
        raw_valence = 2.0 * (positive - negative + self.negativity_weight) / (
            1.0 + self.negativity_weight
        ) - 1.0
        raw_valence -= self.drive_alpha * max_drive_deficit

        raw_arousal = (
            (state['arousal'] + state['excitation']) / 2.0
            - (state['inhibition'] + state['patience']) / 2.0
        )
        raw_arousal += self.drive_gamma * max_drive_deficit

        # dict in-place 갱신 — __setattr__ 우회 (mood/raw_core_affect 자체는
        # 그대로, 안의 키만 변경). 이는 의도적으로 허용된다 (정상 파이프라인).
        self.raw_core_affect['valence'] = float(np.clip(raw_valence, -1.0, 1.0))
        self.raw_core_affect['arousal'] = float(np.clip(raw_arousal, 0.0, 1.0))
        return self.raw_core_affect

    def update_mood(self) -> dict[str, float]:
        """mood(t) = mood(t-1) + η × (raw_core_affect(t) - mood(t-1))."""
        for dim in ('valence', 'arousal'):
            self.mood[dim] += self.eta * (self.raw_core_affect[dim] - self.mood[dim])
        return self.mood

    def set_mood(self, new_mood: dict[str, float], token: object) -> None:
        """spec §8.1: token-gated mood 교체. 직렬화 복원 전용.

        토큰 없이 호출하면 SpecViolation. 정상 파이프라인은 ``update_mood()``.
        """
        assert_low_level(token)
        object.__setattr__(self, 'mood', dict(new_mood))

    def set_raw_core_affect(
        self, new_raw: dict[str, float], token: object
    ) -> None:
        """spec §8.4: token-gated raw_core_affect 교체. 직렬화 복원 전용."""
        assert_low_level(token)
        object.__setattr__(self, 'raw_core_affect', dict(new_raw))
