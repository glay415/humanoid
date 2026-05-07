"""FastPath 유닛 테스트."""

import pytest

from low_level.fast_path import FastPath, FastPathPattern


class TestCheckEmptyPatterns:
    """1. 빈 패턴: 패턴 없을 때 check() -> None."""

    def test_no_patterns_returns_none(self):
        fp = FastPath()
        assert fp.check("anything") is None


class TestPatternMatchSuccess:
    """2. 패턴 매칭 성공: trigger 키워드가 입력에 포함 -> state_changes 반환."""

    def test_trigger_in_input_returns_state_changes(self):
        fp = FastPath()
        changes = {"speed": 1.5}
        fp.register(FastPathPattern(trigger="run", state_changes=changes, confidence=0.8))
        assert fp.check("I want to run fast") == changes


class TestPatternNoMatch:
    """3. 패턴 미매칭: trigger 키워드가 입력에 없음 -> None."""

    def test_trigger_not_in_input_returns_none(self):
        fp = FastPath()
        fp.register(FastPathPattern(trigger="jump", state_changes={"height": 2.0}, confidence=0.8))
        assert fp.check("I want to run fast") is None


class TestConfidenceBelowThreshold:
    """4. confidence 임계값: confidence < threshold -> 매칭 안 됨."""

    def test_low_confidence_returns_none(self):
        fp = FastPath(confidence_threshold=0.7)
        fp.register(FastPathPattern(trigger="run", state_changes={"speed": 1.0}, confidence=0.5))
        assert fp.check("run") is None


class TestConfidenceAboveThreshold:
    """5. confidence 통과: confidence >= threshold -> 매칭 됨."""

    def test_confidence_equal_to_threshold(self):
        fp = FastPath(confidence_threshold=0.6)
        fp.register(FastPathPattern(trigger="run", state_changes={"speed": 1.0}, confidence=0.6))
        assert fp.check("run") == {"speed": 1.0}

    def test_confidence_above_threshold(self):
        fp = FastPath(confidence_threshold=0.6)
        fp.register(FastPathPattern(trigger="run", state_changes={"speed": 1.0}, confidence=0.9))
        assert fp.check("run") == {"speed": 1.0}


class TestMultiplePatterns:
    """6. 복수 패턴: 여러 패턴 등록, 첫 번째 매칭 반환."""

    def test_first_matching_pattern_wins(self):
        fp = FastPath()
        fp.register(FastPathPattern(trigger="run", state_changes={"speed": 1.0}, confidence=0.8))
        fp.register(FastPathPattern(trigger="run", state_changes={"speed": 2.0}, confidence=0.9))
        # 입력에 "run"이 있으므로 첫 번째 패턴의 state_changes 반환
        assert fp.check("run now") == {"speed": 1.0}

    def test_second_pattern_matches_when_first_does_not(self):
        fp = FastPath()
        fp.register(FastPathPattern(trigger="jump", state_changes={"height": 3.0}, confidence=0.8))
        fp.register(FastPathPattern(trigger="run", state_changes={"speed": 1.0}, confidence=0.8))
        assert fp.check("run now") == {"speed": 1.0}


class TestRegister:
    """7. register: 패턴 등록 후 patterns 리스트에 추가됨."""

    def test_register_adds_pattern(self):
        fp = FastPath()
        assert len(fp.patterns) == 0
        pattern = FastPathPattern(trigger="walk", state_changes={"pace": 0.5}, confidence=0.7)
        fp.register(pattern)
        assert len(fp.patterns) == 1
        assert fp.patterns[0] is pattern


class TestStateChangesFormat:
    """8. state_changes 형식: 반환된 dict가 올바른 파라미터 이름과 delta 값 가짐."""

    def test_state_changes_keys_and_values(self):
        fp = FastPath()
        expected = {"velocity": 2.5, "energy": -0.3}
        fp.register(FastPathPattern(trigger="sprint", state_changes=expected, confidence=0.8))
        result = fp.check("sprint ahead")
        assert isinstance(result, dict)
        assert result == expected
        for key in result:
            assert isinstance(key, str)
            assert isinstance(result[key], float)


class TestEmptyInput:
    """9. 빈 입력: 빈 문자열 -> None (어떤 키워드도 포함 안 됨)."""

    def test_empty_string_returns_none(self):
        fp = FastPath()
        fp.register(FastPathPattern(trigger="run", state_changes={"speed": 1.0}, confidence=0.8))
        assert fp.check("") is None


class TestCustomThreshold:
    """10. 커스텀 threshold: threshold=0.9로 설정 -> 0.8 confidence 패턴 무시."""

    def test_high_threshold_ignores_lower_confidence(self):
        fp = FastPath(confidence_threshold=0.9)
        fp.register(FastPathPattern(trigger="run", state_changes={"speed": 1.0}, confidence=0.8))
        assert fp.check("run") is None

    def test_high_threshold_accepts_matching_confidence(self):
        fp = FastPath(confidence_threshold=0.9)
        fp.register(FastPathPattern(trigger="run", state_changes={"speed": 1.0}, confidence=0.95))
        assert fp.check("run") == {"speed": 1.0}
