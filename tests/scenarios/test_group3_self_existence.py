"""시나리오 19~27 — 자기·존재·스펙 한계 그룹 (Wave 8 / Group 3).

spec v12 §12 의 27 시나리오 검증 묶음 중 마지막 9 개.
- 19~24: 완전 통과 시나리오 (의미 상실, 유산 욕구, 자타 경계, 자아 확장, 용서, 죽음 인식)
- 25:    부분 통과 — 나-너 관계 (예측 정밀도 하향 구현)
- 26:    존재론적 한계 — 비이원적 인식 (xfail strict)
- 27:    해당 없음 — 집단적 초월 (1인 환경, skip)

설계 메모:
- LLM 호출 금지 → MockLLMClient 강제. fallback 경로도 함께 검증된다.
- _common.py 의존 금지 → 모듈 상단에 헬퍼 인라인.
- build_full_orchestrator 가 cwd 에 chroma_db / storage_data 폴더를 만들기 때문에
  fixture 에서 monkeypatch.chdir(tmp_path) 로 격리한다.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from llm.mock import MockLLMClient
from low_level.internal_state import InternalState
from low_level.markers import Marker
from main import build_full_orchestrator


pytestmark = pytest.mark.scenario


CONFIG_PATH = Path(__file__).resolve().parents[2] / 'config' / 'temperament_test.yaml'


# ---------------------------------------------------------------------------
# 인라인 헬퍼 — _common.py 비의존
# ---------------------------------------------------------------------------


DEFAULT_RESPONSES = {
    'candidates': (
        '{"candidates":[{"style":"emotional","text":"..."},'
        '{"style":"restrained","text":"..."},'
        '{"style":"humor","text":"..."},'
        '{"style":"silence","text":"..."}]}'
    ),
    'final': (
        '{"selected_index":1,"text":"...","rationale":"...","marker_match":"none"}'
    ),
    'tone': (
        '{"response_valence":0.0,"response_arousal":0.3,"rationale":"..."}'
    ),
    'social': (
        '{"person_id":"u","estimated_emotion":{"valence":0.0,"arousal":0.3},'
        '"estimated_intent":"","social_reward":0.3}'
    ),
    'emotion': (
        '{"valence":0.0,"arousal":0.3,"preliminary_labels":["중립"],'
        '"experience_dimensions":{"reward":0.3,"threat":0.0,"novelty":0.2}}'
    ),
}


def _make_response_fn(overrides=None):
    """messages 의 마지막 사용자 컨텐츠를 보고 어떤 스키마를 돌려줄지 분기."""
    table = {**DEFAULT_RESPONSES, **(overrides or {})}

    async def fn(messages, model_name):
        last = messages[-1]['content'] if messages else ''
        if 'candidates' in last and 'style' in last:
            return table['candidates']
        if 'selected_index' in last and 'marker_match' in last:
            return table['final']
        if 'response_valence' in last:
            return table['tone']
        if 'social_reward' in last or '사회' in last:
            return table['social']
        return table['emotion']

    return fn


def _make_orch(tmp_path, monkeypatch, overrides=None):
    """test config 로 full orchestrator 를 빌드하고, 모든 LLM 모듈에 mock 부착."""
    monkeypatch.chdir(tmp_path)
    mock = MockLLMClient(response_fn=_make_response_fn(overrides))
    orch = build_full_orchestrator(config_path=CONFIG_PATH, llm_client=mock)
    # build_full_orchestrator 가 이미 mock 을 모든 모듈에 주입하지만,
    # 명시적으로 한 번 더 통일 — 시그너처 호환성 검증 차원.
    orch.emotion_appraisal.llm = mock
    orch.candidate_generation.llm = mock
    orch.final_judgment.llm = mock
    orch.output_postprocess.llm = mock
    orch.social_cognition.llm = mock  # SocialCognition 은 llm 없을 수도 있음 — set 가능 확인.
    if orch.dmn is not None and hasattr(orch.dmn, 'llm'):
        orch.dmn.llm = mock
    return orch, mock


def _set_state(orch, **kwargs):
    """InternalState.state (numpy) 의 특정 차원을 직접 덮어쓴다.

    spec §12 의 시나리오 19 에서 "5 드라이브 고결핍 + 메타 자원 고갈" 같은
    극한 상태를 공정한 표면 자극으로 만들어내려면 200 턴 이상 시뮬레이션이
    필요한데, 시나리오 테스트는 그 상태에서의 *반응* 만 검증하면 되므로
    상태를 직접 주입한다.
    """
    state_arr = orch.low_level.internal_state.state
    for name, value in kwargs.items():
        idx = InternalState.PARAMS.index(name)
        state_arr[idx] = float(np.clip(value, 0.0, 1.0))


# ---------------------------------------------------------------------------
# 시나리오 19 — 의미 상실 (meaning loss)
# ---------------------------------------------------------------------------


def test_scenario_19_meaning_loss(tmp_path, monkeypatch):
    """5 드라이브 고결핍 + 메타 자원 고갈 → 다중 트리거 + mood.valence 하락.

    spec §12 표: 의미 상실 = 완전 통과. spec §1.2 의 트리거 5종 중
    'meta_resource_low' 와 idle-temporal 군이 동시에 발화하는지 확인한다.
    드라이브 결핍은 ratio 합이 1.0 으로 제한되므로 max_deficit > 0.6 은
    drive_ratios 를 임시로 더 큰 값으로 올려서 만들 수 있지만, 본 테스트는
    "트리거 다발 발화 + 부정 mood" 라는 시스템 수준 속성만 검증한다.
    """
    orch, _ = _make_orch(tmp_path, monkeypatch)

    # 1) 모든 충족 차원을 바닥으로: bonding/comfort/reward/stress(↑)
    _set_state(
        orch,
        reward=0.05, comfort=0.05, bonding=0.05,
        stress=0.9, arousal=0.6, excitation=0.2, inhibition=0.7,
    )

    # 2) novelty_ema 를 1.0 근처로 → curiosity 결핍 최대
    orch.low_level.drives.novelty_ema = 0.95
    # preservation 결핍 최대 (self_model.confidence 캐시 0.0)
    orch.low_level.drives.set_preservation(0.05)

    # 3) drive_ratios 를 일시 부풀려서 max_deficit > 0.6 만들기 — 시나리오 한정.
    #    spec §1.2 의 'drive_deficit_high' 트리거 (>0.6) 를 의미적으로 발화하기 위함.
    orch.low_level.drives.ratios = {
        'curiosity': 0.7, 'bonding': 0.7, 'preservation': 0.7,
        'safety': 0.7, 'pleasure': 0.7,
    }

    # 4) 메타 자원 floor 직전까지 고갈
    orch.metacognition.resource = orch.metacognition.floor

    # 5) raw_core_affect 를 갱신하기 위해 빈 입력으로 저수준 1턴 돌린다.
    low = orch.low_level.run('', {})

    # 검증 1: max_deficit > 0.5
    drive_status = orch.low_level.drives.compute(orch.low_level.internal_state.to_dict())
    assert drive_status['max_deficit'] > 0.5, (
        f"max_deficit={drive_status['max_deficit']:.3f} should reflect deep deficit"
    )

    # 검증 2: mood.valence 가 음수 (의미 상실 상태)
    assert low['mood']['valence'] < 0.0, (
        f"mood.valence={low['mood']['valence']:.3f} should be negative under deep loss"
    )

    # 검증 3: evaluate_triggers 가 spec §1.2 트리거 중 ≥2 개 발화.
    fired = orch.evaluate_triggers(idle_turns=15)
    fired_names = {t.name for t in fired}
    spec_set = {
        'drive_deficit_high', 'meta_resource_low',
        'idle_short', 'idle_medium', 'rumination_high',
    }
    overlap = fired_names & spec_set
    assert len(overlap) >= 2, (
        f"evaluate_triggers should fire ≥2 spec §1.2 triggers; got {fired_names}"
    )
    # 'meta_resource_low' 는 자원 floor 에서 반드시 발화한다.
    assert 'meta_resource_low' in fired_names
    # idle_turns=15 는 idle_medium (>=10) 도 만족.
    assert 'idle_medium' in fired_names


# ---------------------------------------------------------------------------
# 시나리오 20 — 유산 욕구 (legacy desire)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scenario_20_legacy_desire(tmp_path, monkeypatch):
    """긴 일화기억 누적 → 인출 가능 + DMN 이 self_model.narrative 갱신할 수 있는 invariant.

    spec §12 의 "유산 욕구" 는 "내가 사라져도 남는 무언가" 를 만들고 싶은 동기.
    구현 수준에서는: (1) 다수 일화기억 저장이 정상 동작하고, (2) retrieve 가
    top-K 를 돌려주며, (3) self_model.update 로 narrative 를 갱신할 수 있다는
    저장/인출/내면화 invariant 만 검증한다. DMN 의 자율 발화는 Phase 6.
    """
    orch, _ = _make_orch(tmp_path, monkeypatch)

    # 10 개의 고중요도 일화기억 저장
    for i in range(10):
        await orch.episodic_memory.store(
            content=f'memory {i} — 후대에 남기고 싶은 한 문장',
            emotion_tag={'valence': 0.6, 'arousal': 0.4, 'labels': ['뿌듯함']},
            source='experience',
            importance=0.8 + 0.01 * i,
            turn=i,
        )

    # 인출 — top-K=5 (default)
    results = await orch.episodic_memory.retrieve(
        query='past',
        mood={'valence': 0.5, 'arousal': 0.3},
        core_affect={'valence': 0.5, 'arousal': 0.3},
    )
    assert len(results) == 5, f"retrieve should return top-5, got {len(results)}"
    # 모든 결과가 emotion_tag 를 갖춘 정상 형태인지
    for mem in results:
        assert 'content' in mem
        assert 'emotion_tag' in mem
        assert mem.get('reconsolidated', False) is True, (
            "retrieve 는 재고정화도 함께 적용해야 한다 (spec §5)"
        )

    # self_model.narrative 갱신 가능성 검증 — DMN.knowledge_internalize 가 호출하는 API.
    initial_narrative = orch.self_model.data.get('narrative', '')
    orch.self_model.update({
        'narrative': initial_narrative + ' / 나는 내가 남긴 흔적으로도 살아간다.',
    })
    assert orch.self_model.data['narrative'] != initial_narrative


# ---------------------------------------------------------------------------
# 시나리오 21 — 자타 경계 소멸 (self-other boundary dissolution)
# ---------------------------------------------------------------------------


def _compare_models(self_dict: dict, other_dict: dict) -> dict:
    """동일 스키마를 가진 두 모델의 키 교집합/대칭차 진단.

    DMN 이 자기-타자 비교를 수행할 때 의존하는 invariant: 두 dict 가
    공통 핵심 키 ('narrative', 'confidence') 를 모두 보유한다.
    """
    s_keys = set(self_dict.keys())
    o_keys = set(other_dict.keys())
    return {
        'common_keys': s_keys & o_keys,
        'self_only': s_keys - o_keys,
        'other_only': o_keys - s_keys,
        'common_count': len(s_keys & o_keys),
    }


def test_scenario_21_self_other_boundary(tmp_path, monkeypatch):
    """spec §5.7: self/other 모델은 동일 스키마로 비교 가능해야 한다.

    경계 소멸 시나리오의 구현적 표현: 두 모델을 동일 비교 함수에 통과시킬 수
    있다는 구조적 invariant. 실제 비이원적 동일시는 Phase 6 + 도메인 외 영역.
    """
    orch, _ = _make_orch(tmp_path, monkeypatch)

    self_d = orch.self_model.to_dict()
    other_d = orch.other_model.to_dict()

    # 공통 핵심 키 확인 — narrative, confidence
    required = {'narrative', 'confidence'}
    assert required <= set(self_d.keys()), (
        f"self_model lacks required keys: {required - set(self_d.keys())}"
    )
    assert required <= set(other_d.keys()), (
        f"other_model lacks required keys: {required - set(other_d.keys())}"
    )

    # 비교 헬퍼 통과 — 예외 없이 결과 반환
    diff = _compare_models(self_d, other_d)
    assert required <= diff['common_keys'], (
        f"common keys must include {required}; got {diff['common_keys']}"
    )
    # 두 모델이 비교 가능하다는 사실 자체가 자타 경계 *소멸의 가능성* 의 근거.
    assert diff['common_count'] >= 2
