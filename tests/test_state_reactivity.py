"""페르소나별 stat 변동 가중치 (state_reactivity) 검증.

- 21 yaml 모두에 9-dim state_reactivity 존재 + [0.5, 1.5] clamp
- E vs I 페르소나의 bonding/excitation 분리
- InternalState.update() 가 reactivity 가중치 적용
- backward compat: reactivity_vector=None → ones (동작 변화 없음)
"""

from pathlib import Path

import numpy as np
import pytest
import yaml

from low_level.internal_state import InternalState
from low_level.temperament import Temperament
from scripts.generate_mbti_personas import (
    REACTIVITY_DELTAS,
    REACTIVITY_NEUTRAL,
    reactivity_for,
)


REPO_ROOT = Path(__file__).resolve().parent.parent
PERSONA_DIR = REPO_ROOT / 'config' / 'personas'


PARAMS = InternalState.PARAMS  # ['reward', ..., 'comfort']


def _load_persona(name: str) -> dict:
    return yaml.safe_load((PERSONA_DIR / f'{name}.yaml').read_text(encoding='utf-8'))


def _all_persona_paths() -> list[Path]:
    return sorted(PERSONA_DIR.glob('*.yaml'))


# ---------------------------------------------------------------------------
# 1. yaml 존재성 + 값 범위
# ---------------------------------------------------------------------------

class TestYamlPresence:
    def test_all_21_personas_have_state_reactivity(self):
        paths = _all_persona_paths()
        assert len(paths) == 21, f'expected 21 persona yamls, got {len(paths)}'
        for p in paths:
            cfg = yaml.safe_load(p.read_text(encoding='utf-8'))
            assert 'state_reactivity' in cfg, f'{p.name}: state_reactivity missing'

    def test_state_reactivity_has_all_9_params(self):
        for p in _all_persona_paths():
            cfg = yaml.safe_load(p.read_text(encoding='utf-8'))
            sr = cfg['state_reactivity']
            missing = set(PARAMS) - set(sr.keys())
            assert not missing, f'{p.name}: missing reactivity keys {missing}'
            extra = set(sr.keys()) - set(PARAMS)
            assert not extra, f'{p.name}: unexpected reactivity keys {extra}'

    def test_state_reactivity_values_in_clamp_range(self):
        """모든 값이 [0.5, 1.5] 범위 안에 있어야 한다."""
        for p in _all_persona_paths():
            cfg = yaml.safe_load(p.read_text(encoding='utf-8'))
            sr = cfg['state_reactivity']
            for k, v in sr.items():
                assert 0.5 <= v <= 1.5, f'{p.name} {k}={v} out of [0.5, 1.5]'

    def test_state_reactivity_values_are_floats(self):
        for p in _all_persona_paths():
            cfg = yaml.safe_load(p.read_text(encoding='utf-8'))
            sr = cfg['state_reactivity']
            for k, v in sr.items():
                assert isinstance(v, (int, float)), f'{p.name} {k}={v!r} not numeric'


# ---------------------------------------------------------------------------
# 2. MBTI 축별 분리 — E vs I, F vs T 등
# ---------------------------------------------------------------------------

E_PERSONAS = ['enfp', 'enfj', 'esfp', 'esfj', 'entp', 'entj', 'estp', 'estj']
I_PERSONAS = ['infp', 'infj', 'isfp', 'isfj', 'intp', 'intj', 'istp', 'istj']


class TestMbtiAxisSeparation:
    def test_extrovert_bonding_higher_than_introvert(self):
        """E 페르소나의 bonding reactivity > I 페르소나."""
        e_bonding = [_load_persona(n)['state_reactivity']['bonding'] for n in E_PERSONAS]
        i_bonding = [_load_persona(n)['state_reactivity']['bonding'] for n in I_PERSONAS]
        assert min(e_bonding) > max(i_bonding), (
            f'E bonding {e_bonding} should all exceed I bonding {i_bonding}'
        )

    def test_extrovert_excitation_higher_than_introvert(self):
        e_exc = [_load_persona(n)['state_reactivity']['excitation'] for n in E_PERSONAS]
        i_exc = [_load_persona(n)['state_reactivity']['excitation'] for n in I_PERSONAS]
        assert min(e_exc) > max(i_exc), (
            f'E excitation {e_exc} should all exceed I excitation {i_exc}'
        )

    def test_enfp_vs_istj_canonical_split(self):
        """대표 분리 케이스: ENFP (E+N+F+P) 와 ISTJ (I+S+T+J)."""
        enfp = _load_persona('enfp')['state_reactivity']
        istj = _load_persona('istj')['state_reactivity']
        assert enfp['bonding'] > istj['bonding']
        assert enfp['excitation'] > istj['excitation']
        assert enfp['arousal'] > istj['arousal']
        assert istj['patience'] > enfp['patience']
        assert istj['inhibition'] > enfp['inhibition']
        assert istj['comfort'] > enfp['comfort']

    def test_legacy_personas_inherit_correct_mbti_mapping(self):
        """legacy 5 페르소나는 매핑된 MBTI 와 동일한 reactivity 를 가져야 한다."""
        mapping = {
            'extrovert_warm': 'ENFP',
            'introvert_thoughtful': 'INFJ',
            'playful_companion': 'ESFP',
            'sensitive_empathic': 'INFP',
            'steady_analytical': 'ISTJ',
        }
        for legacy, mbti in mapping.items():
            legacy_rx = _load_persona(legacy)['state_reactivity']
            expected = reactivity_for(mbti)
            for k in PARAMS:
                assert legacy_rx[k] == expected[k], (
                    f'{legacy}.{k} = {legacy_rx[k]} != {mbti}.{k} = {expected[k]}'
                )


# ---------------------------------------------------------------------------
# 3. reactivity_for() 함수 자체 검증
# ---------------------------------------------------------------------------

class TestReactivityForFunction:
    def test_neutral_baseline_is_ones(self):
        for v in REACTIVITY_NEUTRAL.values():
            assert v == 1.0

    def test_neutral_has_all_9_params(self):
        assert set(REACTIVITY_NEUTRAL.keys()) == set(PARAMS)

    def test_all_deltas_target_valid_params(self):
        for axis, deltas in REACTIVITY_DELTAS.items():
            for k in deltas:
                assert k in PARAMS, f'axis {axis} delta target {k} not a valid param'

    @pytest.mark.parametrize('mbti', [
        'INTJ', 'INTP', 'ENTJ', 'ENTP', 'INFJ', 'INFP', 'ENFJ', 'ENFP',
        'ISTJ', 'ISFJ', 'ESTJ', 'ESFJ', 'ISTP', 'ISFP', 'ESTP', 'ESFP',
    ])
    def test_reactivity_for_all_clamped(self, mbti):
        rx = reactivity_for(mbti)
        for k, v in rx.items():
            assert 0.5 <= v <= 1.5, f'{mbti} {k}={v}'
        assert set(rx.keys()) == set(PARAMS)


# ---------------------------------------------------------------------------
# 4. InternalState.update() 가중치 적용
# ---------------------------------------------------------------------------

class TestUpdateAppliesReactivity:
    @pytest.fixture
    def baselines(self):
        return {p: 0.5 for p in PARAMS}

    @pytest.fixture
    def neutral_exp(self):
        # exp 가 0 이면 delta 가 baseline 회귀 + W·deviation 만 — state=baselines 에선 모두 0.
        # nontrivial 자극 필요.
        v = np.zeros(len(InternalState.EXP_DIMS), dtype=np.float64)
        v[0] = 1.0  # reward
        v[1] = 1.0  # novelty
        v[3] = 1.0  # social_reward
        return v

    def test_default_reactivity_is_ones(self, baselines):
        """reactivity_vector=None 이면 ones."""
        eng = InternalState(baselines)
        np.testing.assert_array_equal(eng.reactivity_vector, np.ones(9))

    def test_explicit_ones_matches_default(self, baselines, neutral_exp):
        """ones vector 와 None 이 동일 결과."""
        a = InternalState(baselines)
        b = InternalState(baselines, reactivity_vector=np.ones(9))
        a.update(neutral_exp)
        b.update(neutral_exp)
        np.testing.assert_array_almost_equal(a.state, b.state)

    def test_higher_reactivity_yields_larger_delta(self, baselines, neutral_exp):
        """같은 자극에 reactivity 1.5 가 1.0 보다 큰 변화를 만든다."""
        eng_low = InternalState(baselines, reactivity_vector=np.ones(9))
        eng_high = InternalState(baselines, reactivity_vector=np.full(9, 1.5))

        base_state = eng_low.state.copy()
        eng_low.update(neutral_exp)
        eng_high.update(neutral_exp)

        low_delta = np.abs(eng_low.state - base_state)
        high_delta = np.abs(eng_high.state - base_state)

        # 적어도 한 stat 은 high 가 low 보다 strictly 커야 한다.
        assert np.any(high_delta > low_delta + 1e-9), (
            f'high reactivity should produce larger delta — low={low_delta} high={high_delta}'
        )
        # 변화가 0 이 아닌 stat 에 대해 비율 ≈ 1.5 (Δmax clamp 안 걸린 경우)
        moved = low_delta > 1e-6
        if moved.any():
            ratios = high_delta[moved] / low_delta[moved]
            # clamp 가 일부 적용될 수 있으니 1.0 보다는 크고 1.5 이하여야 한다.
            assert np.all(ratios > 1.0 - 1e-9), f'ratios {ratios} not all > 1'
            assert np.all(ratios <= 1.5 + 1e-9), f'ratios {ratios} not all ≤ 1.5'

    def test_lower_reactivity_yields_smaller_delta(self, baselines, neutral_exp):
        eng_low = InternalState(baselines, reactivity_vector=np.full(9, 0.5))
        eng_high = InternalState(baselines, reactivity_vector=np.ones(9))

        base = eng_low.state.copy()
        eng_low.update(neutral_exp)
        eng_high.update(neutral_exp)

        low_d = np.abs(eng_low.state - base)
        high_d = np.abs(eng_high.state - base)
        assert np.any(high_d > low_d + 1e-9)

    def test_reactivity_vector_wrong_shape_raises(self, baselines):
        with pytest.raises(ValueError):
            InternalState(baselines, reactivity_vector=np.ones(5))


# ---------------------------------------------------------------------------
# 5. Temperament 통합 — yaml → reactivity_vector → InternalState
# ---------------------------------------------------------------------------

class TestTemperamentIntegration:
    def test_temperament_loads_reactivity_from_yaml(self):
        temp = Temperament(PERSONA_DIR / 'enfp.yaml')
        rv = temp.reactivity_vector()
        assert rv is not None
        assert rv.shape == (9,)
        # ENFP bonding (index 7) == 1.5
        assert rv[PARAMS.index('bonding')] == 1.5

    def test_temperament_without_reactivity_returns_none(self, tmp_path):
        """yaml 에 state_reactivity 없으면 None 반환 (backward compat)."""
        yaml_text = """name: "test"
baselines:
  reward: 0.5
  patience: 0.5
  arousal: 0.5
  learning: 0.5
  excitation: 0.5
  inhibition: 0.5
  stress: 0.5
  bonding: 0.5
  comfort: 0.5
drive_ratios:
  curiosity: 0.2
  bonding: 0.2
  preservation: 0.2
  safety: 0.2
  pleasure: 0.2
"""
        cfg = tmp_path / 'nolitherapy.yaml'
        cfg.write_text(yaml_text, encoding='utf-8')
        temp = Temperament(cfg)
        assert temp.reactivity_vector() is None
        assert temp.state_reactivity is None

    def test_enfp_vs_istj_pipeline_diverges(self):
        """ENFP 와 ISTJ 의 같은 exp_vec 변동량이 reactivity 로 분리되는지."""
        enfp_temp = Temperament(PERSONA_DIR / 'enfp.yaml')
        istj_temp = Temperament(PERSONA_DIR / 'istj.yaml')

        # 같은 baselines 로 reactivity 효과만 보기 위해 baselines 통일
        common_bl = {p: 0.5 for p in PARAMS}
        enfp_eng = InternalState(common_bl, reactivity_vector=enfp_temp.reactivity_vector())
        istj_eng = InternalState(common_bl, reactivity_vector=istj_temp.reactivity_vector())

        # bonding 자극 (social_reward) 만 1.0
        exp = np.zeros(len(InternalState.EXP_DIMS), dtype=np.float64)
        exp[InternalState.EXP_DIMS.index('social_reward')] = 1.0

        before = enfp_eng.state.copy()
        enfp_eng.update(exp)
        istj_eng.update(exp)

        bonding_idx = PARAMS.index('bonding')
        enfp_delta = enfp_eng.state[bonding_idx] - before[bonding_idx]
        istj_delta = istj_eng.state[bonding_idx] - before[bonding_idx]

        # ENFP bonding reactivity = 1.5, ISTJ bonding reactivity = 0.6
        # → ENFP delta 가 ISTJ delta 보다 strictly 커야 한다
        assert enfp_delta > istj_delta + 1e-6, (
            f'ENFP bonding Δ {enfp_delta} should exceed ISTJ Δ {istj_delta}'
        )
