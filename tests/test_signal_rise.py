"""SignalRise 단위 테스트.

정밀도 손실 = 자기 인식 해상도 (spec §3.1).
quantize / generate_self_signal / generate_marker_signal / apply_meta_correction.
"""

import pytest

from interface.signal_rise import SignalRise
from low_level.markers import Marker


# ===== 1. RESOLUTION_LEVELS =====

class TestResolutionLevels:
    def test_only_2_3_5_supported(self):
        assert set(SignalRise.RESOLUTION_LEVELS.keys()) == {2, 3, 5}

    def test_resolution_label_counts(self):
        assert len(SignalRise.RESOLUTION_LEVELS[2]) == 2
        assert len(SignalRise.RESOLUTION_LEVELS[3]) == 3
        assert len(SignalRise.RESOLUTION_LEVELS[5]) == 5


# ===== 2. quantize resolution=3 =====

class TestQuantizeResolution3:
    def setup_method(self):
        self.sr = SignalRise(resolution=3)

    def test_low(self):
        out = self.sr.quantize(0.0, 'x')
        assert "낮음" in out
        assert "중간" not in out

    def test_mid(self):
        out = self.sr.quantize(0.5, 'x')
        assert "중간" in out

    def test_high_clamped(self):
        # 1.0 * 3 = 3 → clamp 으로 idx=2 ("높음")
        out = self.sr.quantize(1.0, 'x')
        assert "높음" in out
        # "매우 높음" 은 5단계 라벨이므로 3단계에는 없어야 함
        assert "매우" not in out

    def test_boundary_just_below_one_third(self):
        # 0.333 * 3 = 0.999 → int = 0 → "낮음"
        out = self.sr.quantize(0.333, 'x')
        assert "낮음" in out

    def test_boundary_just_above_one_third(self):
        # 0.34 * 3 = 1.02 → int = 1 → "중간"
        out = self.sr.quantize(0.34, 'x')
        assert "중간" in out


# ===== 3. quantize resolution=2 (binary) =====

class TestQuantizeResolution2:
    def test_binary_labels(self):
        sr = SignalRise(resolution=2)
        # 0.0 → 없음
        assert "없음" in sr.quantize(0.0, 'x')
        # 1.0 → 있음 (clamp)
        assert "있음" in sr.quantize(1.0, 'x')
        # 0.6 * 2 = 1.2 → int = 1 → 있음
        assert "있음" in sr.quantize(0.6, 'x')


# ===== 4. quantize resolution=5 =====

class TestQuantizeResolution5:
    def test_five_step_labels(self):
        sr = SignalRise(resolution=5)
        # 0.0 → "매우 낮음"
        assert "매우 낮음" in sr.quantize(0.0, 'x')
        # 1.0 → "매우 높음" (clamp)
        assert "매우 높음" in sr.quantize(1.0, 'x')


# ===== 5. param_name 포함 =====

class TestParamName:
    def test_param_name_appears_verbatim(self):
        sr = SignalRise(resolution=3)
        out = sr.quantize(0.5, 'reward')
        assert "reward" in out


# ===== 6. generate_self_signal =====

class TestGenerateSelfSignal:
    def setup_method(self):
        self.sr = SignalRise(resolution=3)

    def test_includes_quantized_fragments_per_state_key(self):
        state = {'reward': 0.0, 'stress': 1.0}
        out = self.sr.generate_self_signal(
            state=state, drives={}, raw_core_affect={'valence': 0.5, 'arousal': 0.5},
        )
        # 두 키 모두 라벨링 되어야 함
        assert "reward" in out
        assert "stress" in out

    def test_positive_valence_phrase(self):
        out = self.sr.generate_self_signal(
            state={'reward': 0.5}, drives={},
            raw_core_affect={'valence': 0.4, 'arousal': 0.0},
        )
        assert "전반적 기분이 긍정적" in out

    def test_non_positive_valence_phrase(self):
        out = self.sr.generate_self_signal(
            state={'reward': 0.5}, drives={},
            raw_core_affect={'valence': -0.4, 'arousal': 0.0},
        )
        assert "전반적 기분이 부정적" in out

    def test_non_empty_for_any_state(self):
        out = self.sr.generate_self_signal(
            state={'x': 0.1}, drives={}, raw_core_affect={'valence': 0.0, 'arousal': 0.0},
        )
        assert isinstance(out, str)
        assert len(out) > 0


# ===== 7-10. generate_marker_signal =====

class TestGenerateMarkerSignal:
    def setup_method(self):
        self.sr = SignalRise(resolution=3)

    def test_empty_list(self):
        assert self.sr.generate_marker_signal([]) == "(관련 경험 마커 없음)"

    def test_dataclass_markers(self):
        m1 = Marker(pattern_id='p1', valence=0.8, strength=0.9)
        m2 = Marker(pattern_id='p2', valence=-0.7, strength=0.5)
        out = self.sr.generate_marker_signal([m1, m2])
        # 첫 마커: 접근 + 높은 강도 라벨 (0.9 * 3 = 2.7 → idx=2 → "높음")
        assert "접근" in out
        assert "높음" in out
        # 둘째 마커: 회피
        assert "회피" in out
        # 결합 separator
        assert ", " in out

    def test_dict_markers(self):
        # dict 폴리모피즘 — dataclass 와 동일 결과
        markers = [
            {'valence': 0.8, 'strength': 0.9},
            {'valence': -0.7, 'strength': 0.5},
        ]
        out = self.sr.generate_marker_signal(markers)
        assert "접근" in out
        assert "회피" in out
        assert "높음" in out
        assert ", " in out

    def test_neutral_marker(self):
        m = Marker(pattern_id='p', valence=0.0, strength=0.5)
        out = self.sr.generate_marker_signal([m])
        assert "중립" in out
        assert "접근" not in out
        assert "회피" not in out


# ===== 11. apply_meta_correction =====

class TestApplyMetaCorrection:
    def setup_method(self):
        self.sr = SignalRise(resolution=3, meta_beta=0.08)

    def test_full_resource_no_correction(self):
        raw = {'valence': 0.5, 'arousal': 0.3}
        final = self.sr.apply_meta_correction(raw, meta_resource=1.0)
        assert final['valence'] == pytest.approx(0.5)

    def test_zero_resource_max_correction(self):
        raw = {'valence': 0.5, 'arousal': 0.3}
        final = self.sr.apply_meta_correction(raw, meta_resource=0.0)
        assert final['valence'] == pytest.approx(0.5 - 0.08)

    def test_half_resource_half_correction(self):
        raw = {'valence': 0.5, 'arousal': 0.3}
        final = self.sr.apply_meta_correction(raw, meta_resource=0.5)
        assert final['valence'] == pytest.approx(0.5 - 0.5 * 0.08)

    def test_clamp_to_minus_one(self):
        # raw.valence=-0.99, beta=1.0, meta_resource=0.0 → -0.99 - 1.0 = -1.99 → clamp -1.0
        sr = SignalRise(resolution=3, meta_beta=1.0)
        final = sr.apply_meta_correction({'valence': -0.99, 'arousal': 0.0}, meta_resource=0.0)
        assert final['valence'] == pytest.approx(-1.0)

    def test_does_not_mutate_input(self):
        raw = {'valence': 0.5, 'arousal': 0.3}
        original = dict(raw)
        final = self.sr.apply_meta_correction(raw, meta_resource=0.0)
        assert raw == original
        # 새 dict 인지
        assert final is not raw

    def test_arousal_unchanged(self):
        raw = {'valence': 0.5, 'arousal': 0.42}
        final = self.sr.apply_meta_correction(raw, meta_resource=0.0)
        assert final['arousal'] == pytest.approx(0.42)
