"""Wave 8 시나리오 1~9 (Group 1: 코어 감정 / 사회).

spec v12 §12 의 27개 검증 시나리오 중 첫 9개.
모든 LLM 호출은 MockLLMClient 로 stub. 실제 API 호출 0회.

각 클래스가 한 시나리오를 표현하며 docstring 에 spec 불변량을 한국어로 적었다.
어설트는 "시스템의 emergent 불변량" 을 검증한다 — LLM 가 옳은 텍스트를 만드는지가
아니라, 저수준 수치/메타인지 결정/스토리지 부수효과가 spec 그대로 흘러가는지.

테스트 일부는 spec 문구 그대로의 임계값(예: bonding_deficit > 0.4) 을 만족시키기
위해 baseline + drive_ratios 를 시나리오마다 살짝 다르게 잡는다 (`copy_temperament_yaml`).
"""
from __future__ import annotations

import pytest

from low_level.markers import Marker
from tests.scenarios._common import (
    _build_mocked_orchestrator,
    copy_temperament_yaml,
    make_response_fn,
)


pytestmark = pytest.mark.scenario


# ---------------------------------------------------------------------------
# 1. 열망 (yearning) — bonding 결핍 누적 + 긍정 기억 → 기분 저하, DMN 후보
# ---------------------------------------------------------------------------


class TestScenario01Yearning:
    """열망 — 유대 baseline 이 낮고 social_reward 가 거의 없는 10턴 후
    bonding 결핍이 다른 드라이브를 압도해 max_deficit_drive 가 'bonding'.

    spec invariant:
        bonding_deficit > 0.4 (10턴 누적, drive_ratios.bonding=0.5 가정)
        max_deficit_drive == 'bonding'
        DMN 트리거 'drive_deficit_high' (max_deficit > 0.6) 후보로 등장 가능
    """

    @pytest.fixture
    async def orch(self, tmp_path):
        cfg = copy_temperament_yaml(
            tmp_path,
            name='yearning',
            baseline_overrides={'bonding': 0.05},
            config_overrides={
                'drive_ratios': {
                    'curiosity': 0.15, 'bonding': 0.50,
                    'preservation': 0.10, 'safety': 0.05, 'pleasure': 0.20,
                },
            },
        )
        rfn = make_response_fn(
            emotion={
                'valence': 0.1, 'arousal': 0.3,
                'preliminary_labels': ['그리움'],
                'experience_dimensions': {
                    'reward': 0.1, 'threat': 0.0, 'novelty': 0.1,
                },
            },
            social={
                'person_id': 'u',
                'estimated_emotion': {'valence': 0.0, 'arousal': 0.2},
                'estimated_intent': '',
                'social_reward': 0.05,
            },
        )
        return _build_mocked_orchestrator(tmp_path, response_fn=rfn, config_path=cfg)

    async def test_bonding_deficit_dominates_after_idle_turns(self, orch):
        for _ in range(10):
            await orch.process_conversation_turn('...')

        state = orch.low_level.internal_state.to_dict()
        drives = orch.low_level.drives.compute(state)

        # spec: bonding 결핍이 누적되어 0.4 를 초과한다.
        assert drives['deficits']['bonding'] > 0.4, drives['deficits']
        # 다른 드라이브 결핍은 모두 bonding 보다 작다 → max_deficit_drive == 'bonding'.
        max_drive = max(drives['deficits'].items(), key=lambda kv: kv[1])[0]
        assert max_drive == 'bonding'
        # bonding 자체도 baseline 근방 (사회보상 없음).
        assert state['bonding'] < 0.3


# ---------------------------------------------------------------------------
# 2. 후회 (regret) — 강한 음성 마커 형성 + 재고정화로 valence 더 음수
# ---------------------------------------------------------------------------


class TestScenario02Regret:
    """후회 — 사전 등록된 음성 마커(valence=-0.3) 가 부정 코어어펙트로 3회
    재강화되면 marker_store 의 valence 가 더 음수로 이동한다.

    spec invariant:
        Marker.reinforce(weight=0.3) 를 음성 valence(-0.7) 로 3회 호출하면
        valence: -0.3 → -0.42 → -0.504 → -0.5628 (모두 < -0.4)
        MarkerStore upsert 후 load_all() 결과의 valence 가 동일하게 반영.
    """

    def test_marker_reconsolidation_drives_valence_more_negative(self, tmp_path):
        from storage.marker_store import MarkerStore

        store = MarkerStore(db_path=str(tmp_path / 'markers.db'))
        m = Marker(pattern_id='regret_pattern', valence=-0.3, strength=0.6, age=0)
        store.save(m)

        # 3회 부정 코어어펙트로 재강화.
        for _ in range(3):
            m.reinforce(new_valence=-0.7, new_strength=0.7, weight=0.3)
            store.save(m)

        # 메모리상 valence 검증.
        assert m.valence < -0.4
        # SQLite 영속 상태도 동일.
        loaded = {row['pattern_id']: row for row in store.load_all()}
        assert loaded['regret_pattern']['valence'] < -0.4
        assert loaded['regret_pattern']['valence'] == pytest.approx(m.valence, abs=1e-9)
        store.close()


# ---------------------------------------------------------------------------
# 3. 외로움 (loneliness) — bonding=0.0 baseline + 빈 입력 → mood.valence < -0.1
# ---------------------------------------------------------------------------


class TestScenario03Loneliness:
    """외로움 — 매우 낮은 bonding baseline 에서 social_reward=0 으로 10턴.
    bonding 회복 경로가 없으므로 max_deficit 이 계속 bonding 으로 고정.

    spec invariant:
        mood.valence < -0.1 (negativity_weight=0.6, raw_v 가 강한 음수로 누적)
        bonding_deficit > 0.45 (drive_ratios.bonding=0.5, 결핍 1.0 근처)
        bonding 자체는 baseline 0.0 에서 거의 움직이지 않음.
    """

    @pytest.fixture
    async def orch(self, tmp_path):
        cfg = copy_temperament_yaml(
            tmp_path,
            name='loneliness',
            baseline_overrides={
                'bonding': 0.0, 'reward': 0.3, 'comfort': 0.3,
            },
            config_overrides={
                'drive_ratios': {
                    'curiosity': 0.10, 'bonding': 0.50,
                    'preservation': 0.10, 'safety': 0.10, 'pleasure': 0.20,
                },
            },
        )
        rfn = make_response_fn(
            emotion={
                'valence': -0.05, 'arousal': 0.2,
                'preliminary_labels': ['적막'],
                'experience_dimensions': {
                    'reward': 0.0, 'threat': 0.0, 'novelty': 0.0,
                },
            },
            social={
                'person_id': 'u',
                'estimated_emotion': {'valence': 0.0, 'arousal': 0.2},
                'estimated_intent': '',
                'social_reward': 0.0,
            },
            tone={'response_valence': -0.05, 'response_arousal': 0.2,
                  'rationale': 'flat'},
        )
        return _build_mocked_orchestrator(tmp_path, response_fn=rfn, config_path=cfg)

    async def test_loneliness_drives_mood_negative(self, orch):
        for _ in range(10):
            await orch.process_conversation_turn('...')

        state = orch.low_level.internal_state.to_dict()
        drives = orch.low_level.drives.compute(state)
        mood = orch.low_level.emotion_base.mood

        assert mood['valence'] < -0.1, f"mood not negative: {mood}"
        # bonding 결핍이 다른 모든 드라이브를 압도.
        assert drives['deficits']['bonding'] > 0.45
        max_drive = max(drives['deficits'].items(), key=lambda kv: kv[1])[0]
        assert max_drive == 'bonding'
        # bonding 자체는 baseline=0 근방에서 회복하지 못함.
        assert state['bonding'] < 0.05

