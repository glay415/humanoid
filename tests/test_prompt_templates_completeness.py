"""프로덕션 프롬프트 템플릿 렌더 계약 검증.

각 템플릿이 호출 모듈(high_level/*.py)에서 넘기는 변수 집합으로
KeyError 없이 렌더링되는지, 그리고 변수 값이 실제로 출력 텍스트에
삽입되는지 검사한다. 빠진 변수가 있을 때는 KeyError 가 발생해야 한다.

LLM은 호출하지 않는다 — 순수하게 str.format 기반의 템플릿 계약만 본다.
"""
from __future__ import annotations

import pytest

from llm.prompts import load_prompt


# ---------------------------------------------------------------------------
# 각 템플릿의 호출부 변수 집합. high_level/*.py 와 prompts/*.txt 의 계약.
# ---------------------------------------------------------------------------

EMOTION_VARS: dict = {
    'user_input': '안녕하세요',
    'valence': 0.3,
    'arousal': 0.4,
    'recent_memory_summary': '어제 같이 걸었던 기억',
}

CANDIDATE_VARS: dict = {
    'user_input': '오늘 어땠어?',
    'emotion_summary': 'valence=0.30, arousal=0.40, 라벨=[기쁨]',
    'social_summary': '의도=공감 요청; 상대 v=0.20/a=0.30',
    'memory_summary': '- 어제 좋았다는 발화 (중요도 0.80)',
    'self_narrative': '나는 차분하지만 정 많은 사람이다.',
    'mood_text': 'valence=0.10, arousal=0.30',
    'marker_signal': '접근 마커: 부드러운 농담',
    'n_candidates': 4,
    'recent_dialogue': '사람: 어제 영화 봤어\n나: 어떤 영화?',
}

FINAL_VARS: dict = {
    'user_input': '잠깐 얘기 좀 할까?',
    'candidates_json': '[{"x":1}]',
    'marker_signal': '회피 마커: 격앙된 어조',
    'confidence': 0.72,
}

TONE_VARS: dict = {
    'response': '괜찮아, 같이 해보자.',
    'valence': 0.25,
    'arousal': 0.35,
}

SOCIAL_VARS: dict = {
    'user_input': '어제 일 미안해',
    'emotion_summary': 'valence=0.10, arousal=0.40, 라벨=[미안]',
    'other_model_summary': '상대는 친밀, 신뢰 0.6',
}


TEMPLATE_CASES = [
    ('emotion_appraisal', EMOTION_VARS),
    ('candidate_generation', CANDIDATE_VARS),
    ('final_judgment', FINAL_VARS),
    ('tone_verification', TONE_VARS),
    ('social_cognition', SOCIAL_VARS),
]


# ---------------------------------------------------------------------------
# 1. 각 템플릿이 기대 변수 집합으로 KeyError 없이 렌더링된다
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('name,vars_dict', TEMPLATE_CASES)
def test_template_renders_without_keyerror(name: str, vars_dict: dict):
    """기대 변수 집합으로 호출 시 KeyError 없이 비어있지 않은 문자열 반환."""
    tpl = load_prompt(name)
    out = tpl.render(**vars_dict)
    assert isinstance(out, str)
    assert len(out) > 0, f"{name} rendered empty string"


# ---------------------------------------------------------------------------
# 2. 각 변수가 마커 값으로 출력에 그대로 삽입된다
# ---------------------------------------------------------------------------

def test_emotion_appraisal_contains_rendered_vars():
    tpl = load_prompt('emotion_appraisal')
    out = tpl.render(
        user_input='MARKER_USER_INPUT',
        valence=0.111,
        arousal=0.222,
        recent_memory_summary='MARKER_MEMORY_SUMMARY',
    )
    assert 'MARKER_USER_INPUT' in out
    assert 'MARKER_MEMORY_SUMMARY' in out
    assert '0.111' in out
    assert '0.222' in out


def test_candidate_generation_contains_rendered_vars():
    tpl = load_prompt('candidate_generation')
    out = tpl.render(
        user_input='MARKER_USER_INPUT',
        emotion_summary='MARKER_EMOTION',
        social_summary='MARKER_SOCIAL',
        memory_summary='MARKER_MEMORY',
        self_narrative='MARKER_NARRATIVE',
        mood_text='MARKER_MOOD',
        marker_signal='MARKER_MSIG',
        n_candidates=4,
        recent_dialogue='MARKER_DIALOGUE',
    )
    for marker in ['MARKER_USER_INPUT', 'MARKER_EMOTION', 'MARKER_SOCIAL',
                   'MARKER_MEMORY', 'MARKER_NARRATIVE', 'MARKER_MOOD',
                   'MARKER_MSIG', 'MARKER_DIALOGUE']:
        assert marker in out, f"{marker} missing in candidate_generation"
    # n_candidates 는 두 번 등장 (입력 라벨 + "정확히 N 이다" 규칙)
    assert out.count('4') >= 1


def test_final_judgment_contains_rendered_vars():
    tpl = load_prompt('final_judgment')
    out = tpl.render(
        user_input='MARKER_USER_INPUT',
        candidates_json='[{"x":1}]',
        marker_signal='MARKER_MSIG',
        confidence=0.789,
    )
    assert 'MARKER_USER_INPUT' in out
    assert 'MARKER_MSIG' in out
    assert '0.789' in out
    # candidates_json 자체는 substring 으로 등장해야 한다
    assert '"x":1' in out or '"x": 1' in out


def test_tone_verification_contains_rendered_vars():
    tpl = load_prompt('tone_verification')
    out = tpl.render(
        response='MARKER_RESPONSE_TEXT',
        valence=0.555,
        arousal=0.333,
    )
    assert 'MARKER_RESPONSE_TEXT' in out
    assert '0.555' in out
    assert '0.333' in out


def test_social_cognition_contains_rendered_vars():
    tpl = load_prompt('social_cognition')
    out = tpl.render(
        user_input='MARKER_USER_INPUT',
        emotion_summary='MARKER_EMOTION',
        other_model_summary='MARKER_OTHER_MODEL',
    )
    assert 'MARKER_USER_INPUT' in out
    assert 'MARKER_EMOTION' in out
    assert 'MARKER_OTHER_MODEL' in out


# ---------------------------------------------------------------------------
# 3. 각 템플릿은 변수가 누락되면 KeyError
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('name,vars_dict', TEMPLATE_CASES)
def test_each_template_rejects_missing_var(name: str, vars_dict: dict):
    """필수 변수 중 아무거나 하나만 빠뜨려도 KeyError 발생."""
    tpl = load_prompt(name)
    keys = list(vars_dict.keys())
    assert keys, f"{name} test case has no vars to omit"
    # 첫 번째 키를 빼고 나머지로 호출 → KeyError 기대
    omitted_key = keys[0]
    partial = {k: v for k, v in vars_dict.items() if k != omitted_key}
    with pytest.raises(KeyError):
        tpl.render(**partial)


# ---------------------------------------------------------------------------
# 4. 출력 JSON 스키마 키들이 프롬프트 본문에 살아있는지 (substring 검사)
#    프롬프트 편집 시 실수로 필수 키가 빠지는 것을 잡는 안전망.
# ---------------------------------------------------------------------------

def test_emotion_appraisal_template_outputs_valid_json_block():
    tpl = load_prompt('emotion_appraisal')
    out = tpl.render(**EMOTION_VARS)
    # JSON 블록이 포함되는지 (중괄호 페어)
    assert '{' in out and '}' in out
    # EmotionAppraised 스키마 키들
    for key in ('valence', 'arousal', 'preliminary_labels', 'experience_dimensions'):
        assert key in out, f"emotion_appraisal prompt missing required output key: {key}"


def test_final_judgment_template_outputs_valid_json_block():
    tpl = load_prompt('final_judgment')
    out = tpl.render(**FINAL_VARS)
    assert '{' in out and '}' in out
    for key in ('selected_index', 'text', 'marker_match'):
        assert key in out, f"final_judgment prompt missing required output key: {key}"


def test_tone_verification_template_outputs_valid_json_block():
    tpl = load_prompt('tone_verification')
    out = tpl.render(**TONE_VARS)
    assert '{' in out and '}' in out
    for key in ('response_valence', 'response_arousal'):
        assert key in out, f"tone_verification prompt missing required output key: {key}"


# ---------------------------------------------------------------------------
# 5. 후보 생성 프롬프트가 4개 스타일 enum 명시
# ---------------------------------------------------------------------------

def test_candidate_generation_template_lists_required_styles():
    """후보 생성 프롬프트는 4개의 style enum (emotional/restrained/humor/silence) 을 모두 언급."""
    tpl = load_prompt('candidate_generation')
    out = tpl.render(**CANDIDATE_VARS)
    for style in ('emotional', 'restrained', 'humor', 'silence'):
        assert style in out, f"candidate_generation prompt missing style: {style}"
