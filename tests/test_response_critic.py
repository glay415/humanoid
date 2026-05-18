"""ADR-037 L1 — ResponseCritic (soft-quality critic) 테스트.

스코프:
  * 깨끗한 draft → needs_rewrite False, rewritten None.
  * sycophantic / ontology-recitation draft (MockLLMClient 로 verdict 시뮬)
    → needs_rewrite True + rewritten 반환.
  * LLM 실패 → fail-open (needs_rewrite False, never raises).
  * prompt 변수 shape (draft / user_input / self_narrative inject).
"""
from __future__ import annotations

import json

from high_level.response_critic import CriticResult, ResponseCritic
from llm import MockLLMClient


_NAR = '무뚝뚝하지만 정 있는 사람. 말 짧음.'


async def test_clean_draft_no_rewrite():
    mock = MockLLMClient(responses=[
        json.dumps({"needs_rewrite": False, "rewritten": None,
                    "reason": "clean"}, ensure_ascii=False),
    ])
    c = ResponseCritic(llm_client=mock)
    r = await c.review('응 그럭저럭.', user_input='잘 지내?',
                        self_narrative=_NAR)
    assert r.needs_rewrite is False
    assert r.rewritten is None
    assert r.reason == 'clean'


async def test_sycophantic_draft_gets_rewrite():
    verdict = {
        "needs_rewrite": True,
        "rewritten": "응.",
        "reason": "무게 0 입력에 과한 감탄+강박 follow-up",
    }
    mock = MockLLMClient(responses=[json.dumps(verdict, ensure_ascii=False)])
    c = ResponseCritic(llm_client=mock)
    r = await c.review(
        '와 정말 좋은 질문이에요!! 너무 멋져요. 오늘 또 뭐 하셨어요?',
        user_input='ㅇㅇ',
        self_narrative=_NAR,
    )
    assert r.needs_rewrite is True
    assert r.rewritten == '응.'
    assert 'follow-up' in r.reason


async def test_ontology_recitation_draft_gets_rewrite():
    verdict = {
        "needs_rewrite": True,
        "rewritten": "글쎄, 딱 떠오르는 게 없네.",
        "reason": "존재양식 낭송 tic",
    }
    mock = MockLLMClient(responses=[json.dumps(verdict, ensure_ascii=False)])
    c = ResponseCritic(llm_client=mock)
    r = await c.review(
        '나는 텍스트 안에서 굴러다니는 존재라 그런 기억이 없어...',
        user_input='고향이 어디야?',
        self_narrative=_NAR,
    )
    assert r.needs_rewrite is True
    assert r.rewritten == '글쎄, 딱 떠오르는 게 없네.'


async def test_llm_failure_fail_open():
    """LLM raise → fail-open (needs_rewrite False, never raises)."""
    mock = MockLLMClient()  # 빈 큐 → LLMError
    c = ResponseCritic(llm_client=mock)
    r = await c.review('아무 응답', user_input='hi', self_narrative=_NAR)
    assert r.needs_rewrite is False
    assert r.rewritten is None
    assert r.reason == 'critic_unavailable'


async def test_bad_json_fail_open():
    mock = MockLLMClient(responses=['그냥 평문 응답 (JSON 아님)'])
    c = ResponseCritic(llm_client=mock)
    r = await c.review('draft', user_input='hi', self_narrative=_NAR)
    assert r.needs_rewrite is False
    assert r.reason == 'critic_unavailable'


async def test_needs_rewrite_but_empty_rewritten_falls_open():
    """재작성 약속했는데 비어 있으면 안전하게 원본 유지."""
    mock = MockLLMClient(responses=[
        json.dumps({"needs_rewrite": True, "rewritten": None,
                    "reason": "x"}, ensure_ascii=False),
    ])
    c = ResponseCritic(llm_client=mock)
    r = await c.review('draft', user_input='hi', self_narrative=_NAR)
    assert r.needs_rewrite is False
    assert r.rewritten is None


async def test_empty_draft_no_call():
    mock = MockLLMClient(responses=['{"needs_rewrite": true}'])
    c = ResponseCritic(llm_client=mock)
    r = await c.review('   ', user_input='hi', self_narrative=_NAR)
    assert r.needs_rewrite is False
    assert r.reason == 'empty_draft'
    assert mock.call_log == []


async def test_prompt_contains_inputs():
    mock = MockLLMClient(responses=[
        json.dumps({"needs_rewrite": False, "rewritten": None,
                    "reason": "clean"}, ensure_ascii=False),
    ])
    c = ResponseCritic(llm_client=mock)
    await c.review(
        '검수 대상 본문', user_input='사용자 발화 X',
        self_narrative='페르소나 narrative Y',
        affect_description='짜증 결',
        risk_signals={'self_harm': 0.0},
    )
    user_msg = mock.call_log[0]['messages'][-1]['content']
    assert '검수 대상 본문' in user_msg
    assert '사용자 발화 X' in user_msg
    assert '페르소나 narrative Y' in user_msg
    assert '짜증 결' in user_msg


async def test_uses_small_model_default():
    mock = MockLLMClient(responses=[
        json.dumps({"needs_rewrite": False, "rewritten": None,
                    "reason": "clean"}, ensure_ascii=False),
    ])
    c = ResponseCritic(llm_client=mock)
    await c.review('d', user_input='u', self_narrative=_NAR)
    assert mock.call_log[0]['model_name'] == 'small_model'


def test_result_dataclass_shape():
    r = CriticResult(needs_rewrite=False, rewritten=None, reason='clean')
    assert r.needs_rewrite is False
    assert r.rewritten is None
    assert r.reason == 'clean'


# --- ADR-038 I7 cross-turn mannerism awareness -----------------------------


async def test_recent_turns_tic_on_heavy_draft_gets_rewrite():
    """uniform ㅋㅋ tic + 무게 있는 draft → needs_rewrite True + rewritten."""
    verdict = {
        "needs_rewrite": True,
        "rewritten": "그랬구나. 많이 힘들었겠다.",
        "reason": "I7 무말버릇 — 무게 있는 발화에 무동기 ㅋㅋ 반복",
    }
    mock = MockLLMClient(responses=[json.dumps(verdict, ensure_ascii=False)])
    c = ResponseCritic(llm_client=mock)
    r = await c.review(
        '그랬구나 많이 힘들었겠다 ㅋㅋ',
        user_input='오늘 좀 힘들었어',
        self_narrative=_NAR,
        recent_assistant_turns=[
            '안녕 ㅋㅋ',
            '그건 좀 안 말할래 ㅋㅋ',
            '아 ㅋㅋ 내가 이상하게 말했네',
        ],
    )
    assert r.needs_rewrite is True
    assert r.rewritten == '그랬구나. 많이 힘들었겠다.'
    assert 'I7' in r.reason


async def test_recent_turns_rendered_into_prompt():
    """recent_assistant_turns 가 critic 프롬프트에 주입된다."""
    mock = MockLLMClient(responses=[
        json.dumps({"needs_rewrite": False, "rewritten": None,
                    "reason": "clean"}, ensure_ascii=False),
    ])
    c = ResponseCritic(llm_client=mock)
    await c.review(
        '응 그래.',
        user_input='ㅇㅇ',
        self_narrative=_NAR,
        recent_assistant_turns=['안녕 ㅋㅋ', '그건 좀 안 말할래 ㅋㅋ'],
    )
    user_msg = mock.call_log[0]['messages'][-1]['content']
    assert '안녕 ㅋㅋ' in user_msg
    assert '그건 좀 안 말할래 ㅋㅋ' in user_msg


async def test_back_compat_without_recent_turns():
    """recent_assistant_turns 없으면 ADR-037 동작과 동일 (back-compat)."""
    mock = MockLLMClient(responses=[
        json.dumps({"needs_rewrite": False, "rewritten": None,
                    "reason": "clean"}, ensure_ascii=False),
    ])
    c = ResponseCritic(llm_client=mock)
    r = await c.review('응 그럭저럭.', user_input='잘 지내?',
                       self_narrative=_NAR)
    assert r.needs_rewrite is False
    assert r.rewritten is None
    assert r.reason == 'clean'


async def test_empty_recent_turns_back_compat():
    """빈 리스트도 back-compat — None 과 동일하게 무해."""
    mock = MockLLMClient(responses=[
        json.dumps({"needs_rewrite": False, "rewritten": None,
                    "reason": "clean"}, ensure_ascii=False),
    ])
    c = ResponseCritic(llm_client=mock)
    r = await c.review('응.', user_input='hi', self_narrative=_NAR,
                       recent_assistant_turns=[])
    assert r.needs_rewrite is False
    assert r.reason == 'clean'


async def test_recent_turns_fail_open_on_llm_error():
    """recent_assistant_turns 주어져도 LLM raise → fail-open."""
    mock = MockLLMClient()  # 빈 큐 → LLMError
    c = ResponseCritic(llm_client=mock)
    r = await c.review(
        '그랬구나 ㅋㅋ',
        user_input='오늘 힘들었어',
        self_narrative=_NAR,
        recent_assistant_turns=['안녕 ㅋㅋ', '그래 ㅋㅋ'],
    )
    assert r.needs_rewrite is False
    assert r.rewritten is None
    assert r.reason == 'critic_unavailable'
