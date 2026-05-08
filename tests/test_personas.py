"""페르소나 카탈로그 로더 테스트.

config/personas/*.yaml 5종이 정상 적재되는지, summary 가 형성되는지,
narrative_seed 가 비어있지 않은지 확인.
"""
from __future__ import annotations

from ui.backend import personas as _personas


EXPECTED_IDS = {
    'introvert_thoughtful',
    'extrovert_warm',
    'sensitive_empathic',
    'steady_analytical',
    'playful_companion',
}


def test_list_personas_returns_five_entries():
    items = _personas.list_personas()
    assert len(items) == 5, f"got {[p.id for p in items]}"


def test_persona_ids_unique_and_match_filenames():
    items = _personas.list_personas()
    ids = [p.id for p in items]
    assert set(ids) == EXPECTED_IDS
    assert len(ids) == len(set(ids))


def test_each_persona_has_required_yaml_keys():
    """jitter / build_full_orchestrator 가 의존하는 핵심 키 검증."""
    for pid in EXPECTED_IDS:
        data = _personas.load_persona_yaml(pid)
        assert 'baselines' in data, f"{pid} missing baselines"
        assert 'drive_ratios' in data, f"{pid} missing drive_ratios"
        assert 'name' in data, f"{pid} missing name"
        # 9 baselines
        baselines = data['baselines']
        for key in ('reward', 'patience', 'arousal', 'learning',
                    'excitation', 'inhibition', 'stress', 'bonding', 'comfort'):
            assert key in baselines, f"{pid} baselines missing {key}"
            v = baselines[key]
            assert 0.0 <= v <= 1.0, f"{pid}.{key}={v} out of range"
        # 5 drive_ratios summing to ~1
        drives = data['drive_ratios']
        for name in ('curiosity', 'bonding', 'preservation', 'safety', 'pleasure'):
            assert name in drives, f"{pid} drive_ratios missing {name}"
        total = sum(drives.values())
        assert abs(total - 1.0) < 1e-6, f"{pid} drive_ratios sum={total}"


def test_each_persona_narrative_seed_nonempty():
    for pid in EXPECTED_IDS:
        info = _personas.get_persona(pid)
        assert info.narrative_seed, f"{pid} narrative_seed empty"
        # 최소 길이 — UI 카드/시드용으로 한 문장 이상 기대.
        assert len(info.narrative_seed) > 20


def test_get_persona_unknown_raises_keyerror():
    import pytest
    with pytest.raises(KeyError):
        _personas.get_persona('does_not_exist_persona')


def test_summary_contains_key_baselines_and_traits():
    info = _personas.get_persona('introvert_thoughtful')
    summary = info.summary
    assert 'key_baselines' in summary
    assert 'key_traits' in summary
    # introvert 는 inhibition 이 0.65 (차분)
    assert summary['key_baselines'].get('inhibition', 0.0) > 0.5
    # 형용사 한국어 단어가 들어있어야 함
    assert summary['key_traits'], f"empty traits for {info.id}"
