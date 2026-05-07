"""감정 기저 — raw 코어 어펙트 + 기분 (leaky integral).

저수준 전용. meta_resource 참조 없음 (계층 분리).
final_core_affect 보정은 interface/signal_rise.py가 담당.
"""

import numpy as np


class EmotionBase:
    """raw_core_affect(valence, arousal) 계산 + mood leaky integral."""

    def __init__(
        self,
        mood_decay_eta: float = 0.05,
        negativity_weight: float = 0.6,
        drive_alpha: float = 0.1,
        drive_gamma: float = 0.05,
    ):
        self.raw_core_affect: dict[str, float] = {'valence': 0.0, 'arousal': 0.0}
        self.mood: dict[str, float] = {'valence': 0.0, 'arousal': 0.0}
        self.eta = mood_decay_eta
        self.negativity_weight = negativity_weight
        self.drive_alpha = drive_alpha
        self.drive_gamma = drive_gamma

    def update_raw_core_affect(
        self,
        state: dict[str, float],
        max_drive_deficit: float = 0.0,
    ) -> dict[str, float]:
        """내부 상태 9개 + 드라이브 결핍 → raw 코어 어펙트."""
        positive = (state['reward'] + state['comfort'] + state['bonding']) / 3.0
        negative = state['stress'] * self.negativity_weight
        raw_valence = (positive - negative) * 2.0 - 1.0
        raw_valence -= self.drive_alpha * max_drive_deficit

        raw_arousal = (
            (state['arousal'] + state['excitation']) / 2.0
            - (state['inhibition'] + state['patience']) / 2.0
        )
        raw_arousal += self.drive_gamma * max_drive_deficit

        self.raw_core_affect['valence'] = float(np.clip(raw_valence, -1.0, 1.0))
        self.raw_core_affect['arousal'] = float(np.clip(raw_arousal, 0.0, 1.0))
        return self.raw_core_affect

    def update_mood(self) -> dict[str, float]:
        """mood(t) = mood(t-1) + η × (raw_core_affect(t) - mood(t-1))."""
        for dim in ('valence', 'arousal'):
            self.mood[dim] += self.eta * (self.raw_core_affect[dim] - self.mood[dim])
        return self.mood
