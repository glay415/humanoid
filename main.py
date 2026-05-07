"""humanoid — 인지 아키텍처 v12 진입점.

Phase 1: 저수준 파이프라인 단독 실행 (CLI).
Phase 4~: 대화 루프.
"""

from pathlib import Path

from low_level.internal_state import InternalState
from low_level.emotion_base import EmotionBase
from low_level.drives import Drives
from low_level.markers import MarkerRegistry
from low_level.fast_path import FastPath
from low_level.self_sensing import SelfSensing
from low_level.temperament import Temperament
from low_level.pipeline import LowLevelPipeline
from core.event_bus import EventBus
from core.trigger_registry import TriggerRegistry
from core.orchestrator import Orchestrator
from interface.signal_rise import SignalRise
from interface.experience_descent import ExperienceDescent


CONFIG_DIR = Path(__file__).parent / 'config'


def build_low_level(config_path: Path | str | None = None) -> LowLevelPipeline:
    """저수준 파이프라인 조립. 기질 YAML에서 파라미터 로드."""
    if config_path is None:
        config_path = CONFIG_DIR / 'temperament_default.yaml'

    temperament = Temperament(config_path)
    cfg = temperament.config

    internal_state = InternalState(temperament.baselines)
    assert internal_state.validate_stability(), "W-D 행렬 안정성 검증 실패!"

    emotion_base = EmotionBase(
        mood_decay_eta=cfg.get('mood_decay_eta', 0.05),
        negativity_weight=cfg.get('negativity_weight', 0.6),
        drive_alpha=cfg.get('drive_alpha', 0.1),
        drive_gamma=cfg.get('drive_gamma', 0.05),
    )
    drives = Drives(drive_ratios=cfg['drive_ratios'])
    markers = MarkerRegistry(
        formation_threshold=cfg.get('marker_formation_threshold', 0.7),
        decay_rate=cfg.get('marker_decay_rate', 0.01),
    )
    fast_path = FastPath(
        confidence_threshold=cfg.get('fast_path_confidence_threshold', 0.6),
    )
    self_sensing = SelfSensing()

    return LowLevelPipeline(
        internal_state=internal_state,
        emotion_base=emotion_base,
        drives=drives,
        markers=markers,
        fast_path=fast_path,
        self_sensing=self_sensing,
        temperament=temperament,
    )


def build_orchestrator(
    config_path: Path | str | None = None,
) -> Orchestrator:
    """오케스트레이터 조립."""
    low_level = build_low_level(config_path)
    cfg = low_level.temperament.config

    return Orchestrator(
        low_level=low_level,
        event_bus=EventBus(),
        trigger_registry=TriggerRegistry(),
        signal_rise=SignalRise(
            resolution=cfg.get('self_awareness_resolution', 3),
            meta_beta=cfg.get('meta_beta', 0.08),
        ),
        experience_descent=ExperienceDescent(),
        auto_encoding_threshold=cfg.get('auto_encoding_threshold', 1.2),
    )


def main():
    """Phase 1 CLI: 경험 벡터를 수동 주입하며 상태 변화 관찰."""
    orch = build_orchestrator()
    print("=== humanoid v12 — Phase 1: 저수준 파이프라인 ===")
    print(f"안정성 검증: PASS")
    print(f"초기 상태: {orch.low_level.internal_state.to_dict()}")
    print()
    print("경험 벡터를 입력하세요 (reward,novelty,threat,social_reward,goal_progress)")
    print("예: 0.8,0.3,0.0,0.5,0.2  |  빈 줄 = 무입력 턴  |  'q' = 종료")
    print()

    while True:
        try:
            line = input(f"[턴 {orch.turn_number + 1}] > ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if line.lower() == 'q':
            break

        # 경험 벡터 파싱
        if line:
            try:
                values = [float(v) for v in line.split(',')]
                assert len(values) == 5, "5개 값 필요"
                exp = dict(zip(InternalState.EXP_DIMS, values))
            except (ValueError, AssertionError) as e:
                print(f"  파싱 오류: {e}")
                continue
        else:
            exp = {}

        orch.prev_experience = exp
        result = orch.run_low_level_only()

        # 출력
        state = result['state']
        ca = result['raw_core_affect']
        mood = result['mood']
        drives = result['drives']['fulfillment']
        max_def = result['drives']['max_deficit']

        print(f"  상태: { {k: round(v, 3) for k, v in state.items()} }")
        print(f"  코어어펙트: v={ca['valence']:.3f}, a={ca['arousal']:.3f}")
        print(f"  기분: v={mood['valence']:.3f}, a={mood['arousal']:.3f}")
        print(f"  드라이브: { {k: round(v, 3) for k, v in drives.items()} }")
        print(f"  최대결핍: {max_def:.3f}")
        print()


if __name__ == '__main__':
    main()
