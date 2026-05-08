"""저수준 고정 파이프라인 — 1→2→3→4→5 순서.

오케스트레이터 없이도 독립 작동 가능.
"""

from low_level.internal_state import InternalState
from low_level.emotion_base import EmotionBase
from low_level.drives import Drives
from low_level.markers import MarkerRegistry
from low_level.fast_path import FastPath
from low_level.self_sensing import SelfSensing
from low_level.temperament import Temperament


class LowLevelPipeline:
    """저수준 고정 파이프라인. 매 턴 시작 전 실행."""

    def __init__(
        self,
        internal_state: InternalState,
        emotion_base: EmotionBase,
        drives: Drives,
        markers: MarkerRegistry,
        fast_path: FastPath,
        self_sensing: SelfSensing,
        temperament: Temperament,
    ):
        self.internal_state = internal_state
        self.emotion_base = emotion_base
        self.drives = drives
        self.markers = markers
        self.fast_path = fast_path
        self.self_sensing = self_sensing
        self.temperament = temperament

    def run(self, raw_input: str, prev_experience: dict) -> dict:
        """매 턴 시작 전 고정 순서 실행 (1→2→3→4→5)."""

        # 1. 빠른 경로 체크
        fast_result = self.fast_path.check(raw_input)
        if fast_result:
            self.internal_state.apply_fast_path(fast_result)

        # 2. 내부 상태 업데이트 (이전 턴 경험 벡터 반영)
        exp_vec = InternalState.experience_dict_to_vector(prev_experience)
        state = self.internal_state.update(exp_vec)
        state_dict = self.internal_state.to_dict()

        # 3. 드라이브 충족도 계산
        if 'novelty' in prev_experience:
            self.drives.update_novelty_ema(prev_experience['novelty'])
        drive_status = self.drives.compute(state_dict)

        # 4. 감정 기저 업데이트
        raw_core_affect = self.emotion_base.update_raw_core_affect(
            state_dict, drive_status['max_deficit']
        )
        mood = self.emotion_base.update_mood()

        # 5. 자기감지
        self_signal = self.self_sensing.generate(
            state_dict, drive_status, raw_core_affect
        )

        # 기질 표류 (매 턴) + InternalState 기저선 동기화 (audit α1)
        self.temperament.drift(self.internal_state.state)
        self.internal_state.set_baselines(self.temperament.baselines)

        return {
            'state': state_dict,
            'raw_core_affect': raw_core_affect,
            'mood': mood,
            'drives': drive_status,
            'self_signal': self_signal,
            'fast_path_triggered': fast_result is not None,
        }
