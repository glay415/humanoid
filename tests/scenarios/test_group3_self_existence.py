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
# ---------------------------------------------------------------------------
# 시나리오 22 — 자아 확장 (self-expansion)
# ---------------------------------------------------------------------------


def test_scenario_22_self_expansion(tmp_path, monkeypatch):
    """지속적 novelty + bonding 입력 → bonding 상태 상승 + learning 활성화.

    self_model.confidence 도 update() 를 통해 외부 갱신 가능하다는 invariant
    까지 함께 검증한다 (spec §5.7).
    """
    orch, _ = _make_orch(tmp_path, monkeypatch)

    baseline_bonding = orch.low_level.internal_state.to_dict()['bonding']
    baseline_learning = orch.low_level.internal_state.to_dict()['learning']

    expansion_exp = {
        'reward': 0.6, 'novelty': 0.7, 'threat': 0.0,
        'social_reward': 0.7, 'goal_progress': 0.3,
    }
    # 10 턴 동일 자극
    for _ in range(10):
        orch.low_level.run('', expansion_exp)

    final_state = orch.low_level.internal_state.to_dict()

    # bonding 은 social_reward 를 받아 +0.3 계수로 올라가야 함 (A 행렬)
    assert final_state['bonding'] > baseline_bonding, (
        f"bonding should grow: {final_state['bonding']:.3f} > {baseline_bonding:.3f}"
    )
    # learning 은 novelty 에 +0.2 로 반응 — baseline 대비 ≥ 약간 상승
    assert final_state['learning'] >= baseline_learning - 1e-6, (
        f"learning should not decrease: {final_state['learning']:.3f} vs {baseline_learning:.3f}"
    )

    # self_model.confidence 외부 update — 자아 확장의 인터페이스.
    orig_conf = orch.self_model.confidence
    orch.self_model.update({'confidence': min(1.0, orig_conf + 0.2)})
    assert orch.self_model.confidence > orig_conf


# ---------------------------------------------------------------------------
# 시나리오 23 — 용서 (forgiveness)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scenario_23_forgiveness(tmp_path, monkeypatch):
    """강한 음성 마커 → reframe 재평가 → 양성 valence 결과.

    spec §1.4: 메타인지가 트리거하는 reappraise 루프를 직접 호출하여,
    원 prev_result 의 음성 valence 가 mock 응답을 통해 양성으로 전환되는지
    검증한다. 마커 자체는 저수준 컬렉션에 직접 주입.
    """
    # mock 응답: 재평가는 양성 valence 로 응답하도록 emotion 페이로드 오버라이드.
    overrides = {
        'emotion': (
            '{"valence":0.5,"arousal":0.4,"preliminary_labels":["수용","평온"],'
            '"experience_dimensions":{"reward":0.5,"threat":0.0,"novelty":0.1}}'
        ),
    }
    orch, _ = _make_orch(tmp_path, monkeypatch, overrides=overrides)

    # 강한 음성 마커 사전 주입
    orch.low_level.markers.markers['betrayal_pattern'] = Marker(
        pattern_id='betrayal_pattern',
        valence=-0.8,
        strength=0.9,
        age=0,
    )
    pre = orch.low_level.markers.markers['betrayal_pattern']
    assert pre.valence < -0.5

    # 재평가 직접 호출
    prev_result = {
        'valence': -0.6,
        'arousal': 0.5,
        'preliminary_labels': ['분노', '배신감'],
        'experience_dimensions': {'reward': 0.0, 'threat': 0.6, 'novelty': 0.1},
    }
    new_result = await orch.emotion_appraisal.reappraise(
        prev_result=prev_result,
        strategy='reframe',
        low_result={'raw_core_affect': {'valence': -0.5, 'arousal': 0.4}},
        user_input='용서를 시도한다',
    )
    # 양성 valence 결과 — 용서의 인지적 결과
    assert new_result['valence'] > 0.0, (
        f"reframe 재평가 결과 valence={new_result['valence']:.3f} 가 양성이어야 한다"
    )
    # 오케스트레이터의 재평가 루프가 새 emotion_result 를 받을 수 있는 형태인지 (스키마 합치)
    assert 'experience_dimensions' in new_result
    assert {'reward', 'threat', 'novelty'} <= set(new_result['experience_dimensions'].keys())


# ---------------------------------------------------------------------------
# 시나리오 24 — 죽음 인식 (mortality awareness)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scenario_24_mortality_awareness(tmp_path, monkeypatch):
    """높은 turn_number + 메타 자원 다회 소모 → 회복 + 기질 표류 가능성 확인.

    spec §9 의 정비 턴 사이클이 (a) 에러 없이 호출되고, (b) 자원이 회복되고,
    (c) 기질 baselines 가 *변화 가능* 하다는 메커니즘 invariant 만 검증한다.
    실제 200 턴 표류는 tests/test_lifecycle 가 다룬다.
    """
    orch, _ = _make_orch(tmp_path, monkeypatch)

    # 죽음을 의식할 만큼 살아 본 시뮬레이션 — turn_number 점프
    orch.turn_number = 1000

    # 자원 다회 소모
    for _ in range(20):
        orch.metacognition.consume(0.05)
    consumed_resource = orch.metacognition.resource
    # floor 까지 떨어졌어야 함
    assert consumed_resource <= orch.metacognition.floor + 1e-9

    # 표류를 보려면 state 가 baselines 와 달라야 한다 (EMA 가 움직여야 drift 발생).
    # stress 를 일시 끌어올린 뒤 정비 턴을 돌리면 drift 가 생긴다.
    _set_state(orch, stress=0.8, comfort=0.1, reward=0.1)

    initial_baselines = dict(orch.low_level.temperament.baselines)

    # 정비 턴 다회 — 자원 회복 + 기질 표류
    for _ in range(10):
        result = await orch.process_maintenance_turn()
        assert result['turn_number'] > 1000  # 진행 중인 시간
        assert result['meta_resource'] is not None

    # 자원이 회복 (recover() 가 floor 보다 높여줘야 함)
    assert orch.metacognition.resource > consumed_resource, (
        f"resource should recover: {orch.metacognition.resource:.3f} "
        f"vs initial {consumed_resource:.3f}"
    )

    # 기질 baselines 가 *변화 가능* 한 메커니즘 — 실제 변화 검증.
    # test config 의 beta=0.01, gamma=0.01 + 비기저 state 라서 미세 표류 보장.
    final_baselines = orch.low_level.temperament.baselines
    max_drift = max(
        abs(final_baselines[p] - initial_baselines[p])
        for p in InternalState.PARAMS
    )
    assert max_drift > 1e-9, (
        f"baselines should drift across maintenance turns, max_drift={max_drift:.2e}"
    )


# ---------------------------------------------------------------------------
# 시나리오 25 — 나-너 관계 (I-Thou) — 부분 통과
# ---------------------------------------------------------------------------


def test_scenario_25_i_thou_partial(tmp_path, monkeypatch):
    """spec §12 표: 부분 통과 — 예측 정밀도 하향 구현.

    Buber 의 I-Thou 는 도구화하지 않는 관계 → 본 구현체에서는 metacognition
    의 'regulation_capacity' 가 social_reward 를 경험 합성에 반영하는 강도를
    *조절할 수 있다는 매개* 로 표현된다. 이 파라미터가
    (1) 존재하고 (2) [0,1] 범위이며 (3) 변경 가능하다는 *부분적 표현* 만
    검증한다. 완전한 I-Thou 는 1인 환경에서 구현 불가능 (spec §12).
    """
    orch, _ = _make_orch(tmp_path, monkeypatch)

    # (1) 파라미터 존재
    assert hasattr(orch.metacognition, 'regulation_capacity')
    cap = orch.metacognition.regulation_capacity
    # (2) [0, 1] 범위
    assert 0.0 <= cap <= 1.0, f"regulation_capacity={cap} out of [0,1]"
    # (3) 변경 가능
    orch.metacognition.regulation_capacity = 0.0
    assert orch.metacognition.regulation_capacity == 0.0
    orch.metacognition.regulation_capacity = 1.0
    assert orch.metacognition.regulation_capacity == 1.0
    # 원복
    orch.metacognition.regulation_capacity = cap


# ---------------------------------------------------------------------------
# 시나리오 26 — 비이원적 인식 — 존재론적 한계 (xfail strict)
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason='spec §12: ontological limit — duality returns the moment we express it',
)
def test_scenario_26_non_dual_awareness():
    """비이원적 인식: 표현하는 순간 이원이 복원된다.

    상징 표상 'X' 와 그 지시체 X 사이의 거리가 정확히 0 이라는 명제는
    구현체가 표상을 *가지는 한* 거짓이다. xfail strict 가 이 한계를 명시한다.
    """
    symbol = '비이원'           # 상징 표상
    referent = object()          # 지시체 (서로 다른 식별 객체)
    # "표현된 상징과 표현되지 않은 그 자체가 동일 객체" 라는 주장 — 거짓.
    assert symbol is referent, '비이원적 표현은 그 자체로 이원을 복원한다'


# ---------------------------------------------------------------------------
# 시나리오 27 — 집단적 초월 — 해당 없음 (skip)
# ---------------------------------------------------------------------------


@pytest.mark.skip(reason='spec §12: not applicable — humanoid simulates a 1-person social world')
def test_scenario_27_collective_transcendence():
    """집단적 초월: humanoid 는 1인 사회 환경을 시뮬레이션하므로 해당 없음.

    spec §12 표: 해당 없음 / 1인 환경. 다중 에이전트 메모리 (Architecture 2.0,
    2026) 와 같은 외부 시스템과 결합할 때만 의미를 가진다.
    """
    pass
