"""ADR-035 — affect_translator (state 숫자 → 한국어 정성 묘사) 테스트.

스코프:
  * AffectTranslator.translate prompt 변수 shape (state/mood/raw_core_affect).
  * model_name + reasoning_effort 가 LLM 호출에 정확히 전달.
  * 결과 strip 처리.
  * stream_unified_turn 의 병렬 gather wiring — memory_retrieval 과 동시 호출,
    실패 시 graceful (None) fallback.
  * unified_response.stream 가 affect_description 을 prompt 변수로 inject.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from high_level.affect_translator import AffectTranslator
from high_level.unified_response import UnifiedResponse
from llm import LLMError, MockLLMClient
from main import build_full_orchestrator


# ---------------------------------------------------------------------------
# AffectTranslator unit
# ---------------------------------------------------------------------------


_NEUTRAL_STATE = {
    'reward': 0.5, 'patience': 0.5, 'arousal': 0.5, 'learning': 0.5,
    'excitation': 0.5, 'inhibition': 0.5, 'stress': 0.5, 'bonding': 0.5,
    'comfort': 0.5,
}
_NEUTRAL_MOOD = {'valence': 0.0, 'arousal': 0.0}
_NEUTRAL_RAW = {'valence': 0.0, 'arousal': 0.0}


async def test_translate_returns_stripped_text():
    """LLM 출력의 leading/trailing whitespace 는 strip."""
    mock = MockLLMClient(responses=['  짜증·날카로움 부글거리는 상태.  \n'])
    t = AffectTranslator(llm_client=mock)
    out = await t.translate(_NEUTRAL_STATE, _NEUTRAL_MOOD, _NEUTRAL_RAW)
    assert out == '짜증·날카로움 부글거리는 상태.'


async def test_translate_includes_state_values_in_prompt():
    """rendered prompt 가 9-dim + mood + raw 값을 정확히 담음."""
    mock = MockLLMClient(responses=['차분·여유.'])
    t = AffectTranslator(llm_client=mock)
    await t.translate(
        state={**_NEUTRAL_STATE, 'stress': 0.85, 'inhibition': 0.15},
        mood={'valence': -0.4, 'arousal': 0.6},
        raw_core_affect={'valence': -0.5, 'arousal': 0.7},
    )
    assert len(mock.call_log) == 1
    user_msg = mock.call_log[0]['messages'][-1]['content']
    assert 'stress=0.85' in user_msg
    assert 'inhibition=0.15' in user_msg
    assert 'valence=-0.40' in user_msg
    assert 'arousal=0.60' in user_msg
    assert 'valence=-0.50' in user_msg


async def test_translate_uses_small_model_default():
    """default model = small_model. mini LLM 빠른 응답이 목적."""
    mock = MockLLMClient(responses=['차분.'])
    t = AffectTranslator(llm_client=mock)
    await t.translate(_NEUTRAL_STATE, _NEUTRAL_MOOD, _NEUTRAL_RAW)
    assert mock.call_log[0]['model_name'] == 'small_model'


async def test_translate_propagates_llm_error():
    """LLM 실패 → LLMError raise. 호출자가 fallback 결정."""
    mock = MockLLMClient()  # 빈 큐 → LLMError
    t = AffectTranslator(llm_client=mock)
    with pytest.raises(LLMError):
        await t.translate(_NEUTRAL_STATE, _NEUTRAL_MOOD, _NEUTRAL_RAW)


async def test_translate_explicit_model_name_override():
    mock = MockLLMClient(responses=['ok'])
    t = AffectTranslator(llm_client=mock)
    await t.translate(_NEUTRAL_STATE, _NEUTRAL_MOOD, _NEUTRAL_RAW, model_name='dmn_model')
    assert mock.call_log[0]['model_name'] == 'dmn_model'


# ---------------------------------------------------------------------------
# UnifiedResponse — affect_description inject
# ---------------------------------------------------------------------------


async def test_unified_response_injects_affect_description():
    """affect_description 인자가 prompt 변수로 inject 됨."""
    mock = MockLLMClient(responses=['응.'])
    ur = UnifiedResponse(llm_client=mock)
    chunks: list[str] = []
    async for c in ur.stream(
        user_input='안녕',
        self_narrative='nar',
        recent_dialogue_text='',
        mood_text='v=0,a=0',
        raw_valence=0.0,
        raw_arousal=0.0,
        internal_state_summary='',
        marker_signal='',
        memory_summary='',
        affect_description='짜증·날카로움 부글거림. 변명 결 어울리지 않음.',
    ):
        chunks.append(c)
    assert chunks == ['응.']
    user_msg = mock.call_log[0]['messages'][-1]['content']
    assert '짜증·날카로움 부글거림' in user_msg
    assert '변명 결 어울리지 않음' in user_msg


async def test_unified_response_none_affect_description_uses_placeholder():
    """affect_description=None 이면 prompt 의 해당 라인이 placeholder 로."""
    mock = MockLLMClient(responses=['응.'])
    ur = UnifiedResponse(llm_client=mock)
    async for _ in ur.stream(
        user_input='안녕',
        self_narrative='nar',
        recent_dialogue_text='',
        mood_text='v=0,a=0',
        raw_valence=0.0,
        raw_arousal=0.0,
        internal_state_summary='',
        marker_signal='',
        memory_summary='',
        affect_description=None,
    ):
        pass
    user_msg = mock.call_log[0]['messages'][-1]['content']
    assert '정성 묘사 미확립' in user_msg


# ---------------------------------------------------------------------------
# Orchestrator — gather wiring + graceful fallback
# ---------------------------------------------------------------------------


@pytest.fixture
def orch(tmp_path: Path):
    return build_full_orchestrator(
        llm_client=MockLLMClient(),
        storage_root=tmp_path / 'inst',
    )


async def test_orchestrator_calls_affect_translator_each_turn(tmp_path: Path):
    """stream_unified_turn 1턴 → AffectTranslator.translate 1 호출."""
    # response_fn 으로 모든 LLM 호출에 동일 응답 — affect_translator + unified_response
    # 둘 다 fallback 없이 정상 처리.
    async def _resp_fn(messages, model_name):
        return '짜증·날카로움. 변명 결 X.'

    orch = build_full_orchestrator(
        llm_client=MockLLMClient(response_fn=_resp_fn),
        storage_root=tmp_path / 'inst',
    )

    # affect_translator 인스턴스를 spy 로 감싸 호출 카운트 확인.
    real_translate = orch.affect_translator.translate
    spy = AsyncMock(side_effect=real_translate)
    orch.affect_translator.translate = spy

    await orch.stream_unified_turn('안녕')
    assert spy.await_count == 1
    # state / mood / raw_core_affect 인자 shape 검증 — 9-dim 키 모두 있어야.
    kwargs = spy.await_args.kwargs
    state_arg = kwargs.get('state') or spy.await_args.args[0]
    for k in ('reward', 'stress', 'bonding', 'comfort'):
        assert k in state_arg


async def test_orchestrator_falls_back_gracefully_when_affect_fails(tmp_path: Path):
    """affect_translator LLM 실패 시 turn 은 계속 진행 (None 으로 fallback)."""
    async def _resp_fn(messages, model_name):
        # unified_response 만 응답하고 affect_translator 는 fail 시뮬레이트.
        sys_content = messages[0]['content'] if messages else ''
        if '내면 정성 번역기' in sys_content:
            raise LLMError('simulated affect translator failure')
        return '응.'

    orch = build_full_orchestrator(
        llm_client=MockLLMClient(response_fn=_resp_fn),
        storage_root=tmp_path / 'inst',
    )
    result = await orch.stream_unified_turn('안녕')
    # turn 자체는 정상 종료.
    assert result['turn_number'] == 1
    assert result['response']  # 빈 응답이라도 something


async def test_orchestrator_skips_affect_translator_if_not_wired(tmp_path: Path):
    """affect_translator=None (legacy) 인 orchestrator 도 정상 동작."""
    async def _resp_fn(messages, model_name):
        return '응.'

    orch = build_full_orchestrator(
        llm_client=MockLLMClient(response_fn=_resp_fn),
        storage_root=tmp_path / 'inst',
    )
    orch.affect_translator = None  # legacy 호환 시뮬레이트.

    result = await orch.stream_unified_turn('안녕')
    assert result['turn_number'] == 1


# ---------------------------------------------------------------------------
# ADR-036 — anti-sycophancy: 반응 무게 예산
# ---------------------------------------------------------------------------


async def test_translate_prompt_contains_reaction_weight_framing():
    """ADR-036: rendered affect_translator prompt 가 *반응 무게* (정보+정서+관계)
    framing + 이번 턴 사용자 발화를 담아야 한다 (blacklist 아닌 비례 원칙)."""
    mock = MockLLMClient(responses=['평탄한 결. 입력 무게 거의 0 — 짧고 평탄하게.'])
    t = AffectTranslator(llm_client=mock)
    await t.translate(
        _NEUTRAL_STATE, _NEUTRAL_MOOD, _NEUTRAL_RAW, user_input='안녕',
    )
    assert len(mock.call_log) == 1
    user_msg = mock.call_log[0]['messages'][-1]['content']
    # 반응 무게 / 비례 framing 이 prompt 에 들어가야.
    assert '반응 무게' in user_msg
    assert ('정보' in user_msg and '정서' in user_msg and '관계' in user_msg)
    # 이번 턴 사용자 발화가 무게 산출용으로 prompt 에 inject.
    assert '안녕' in user_msg
    # system message 도 비례 원칙을 반영.
    sys_msg = mock.call_log[0]['messages'][0]['content']
    assert '비례' in sys_msg


async def test_translate_user_input_optional_default():
    """user_input 미전달(기존 orchestrator 호출 형태) 도 정상 — 시그니처 계약
    불변. 무게 framing 은 9-dim 만으로도 prompt 에 유지."""
    mock = MockLLMClient(responses=['차분·여유.'])
    t = AffectTranslator(llm_client=mock)
    # ADR-035 기존 호출 형태 (user_input 없음) 그대로.
    out = await t.translate(_NEUTRAL_STATE, _NEUTRAL_MOOD, _NEUTRAL_RAW)
    assert out == '차분·여유.'
    user_msg = mock.call_log[0]['messages'][-1]['content']
    assert '반응 무게' in user_msg


async def test_orchestrator_cold_start_greeting_completes_with_affect(tmp_path: Path):
    """ADR-036 behavioral: cold-start '안녕' 한 턴이 에러 없이 완결되고
    affect_translator 가 호출된다 (반응 무게 예산 경로 정상 통합)."""
    async def _resp_fn(messages, model_name):
        sys_content = messages[0]['content'] if messages else ''
        if '내면 정성 번역기' in sys_content:
            # affect_translator: 정성 묘사 + 반응 무게 권고 묶음.
            return ('특별히 끌리는 것 없는 평탄한 결. 입력 무게 거의 0 (인사), '
                    '관계 초기라 가용 온기 낮음 — 짧고 평탄하게, 칭찬·되묻기 '
                    'follow-up 부적절.')
        return '응.'

    orch = build_full_orchestrator(
        llm_client=MockLLMClient(response_fn=_resp_fn),
        storage_root=tmp_path / 'inst',
    )

    real_translate = orch.affect_translator.translate
    spy = AsyncMock(side_effect=real_translate)
    orch.affect_translator.translate = spy

    result = await orch.stream_unified_turn('안녕')

    # 턴 정상 완결.
    assert result['turn_number'] == 1
    assert result['response']
    # affect_translator 가 이번 턴에 호출됨.
    assert spy.await_count == 1
