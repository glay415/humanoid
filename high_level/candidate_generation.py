"""③ 후보 생성 — 큰 모델 LLM.

감정벡터 + 상대상태 + 기억 + 자기모델 + 기분 → 후보 N개.

설계 메모:
- system 메시지에 역할 지시(어떤 모듈인지, JSON-only, 후보 enum/순서 강제)를 두고,
  user 메시지에 prompts/candidate_generation.txt 렌더 결과를 둔다.
- 스키마 검증은 LLMClient.complete_json 이 CandidatesResponse 로 처리.
- 구조 dict들은 _fmt_* 헬퍼들이 짧은 한국어 문자열로 압축해 프롬프트에 박는다.
  None/빈 값을 받아도 KeyError 없이 "(정보 없음)" 류의 폴백을 반환.
"""
from __future__ import annotations

from interface.schemas import CandidatesResponse
from llm.client import LLMClient
from llm.prompts import load_prompt


_SYSTEM_MESSAGE = (
    "당신은 인지 아키텍처의 '후보 응답 생성(candidate generation)' 모듈이다. "
    "사용자 발화 + 감정/사회/기억/자기모델/기분/마커 컨텍스트를 종합해 "
    "결이 다른 응답 후보를 생성한다. "
    "후보 순서는 반드시 emotional → restrained → humor → silence 이며, "
    "각 후보는 style(enum) 과 text 필드만 가진다. "
    "출력은 오직 한 개의 JSON 객체이며, 자연어 설명·마크다운 코드펜스·추가 키를 금지한다."
)


def _intensity_label(value: float, axis: str = "valence") -> str:
    """수치를 정성 강도 라벨로. axis='valence' [-1, 1], 'arousal'/0to1 [0, 1].

    LLM 이 0.5 와 0.9 를 톤 차이로 인식하도록 강도 앵커를 자연어로 박는다.
    숫자만으로는 평탄화되어 saturation 이 출력에 안 보임 (audit 후속 — wave15A).
    """
    if axis == "valence":
        v = max(-1.0, min(1.0, value))
        if v >= 0.7: return "매우 강한 긍정"
        if v >= 0.45: return "분명한 긍정"
        if v >= 0.15: return "잔잔한 긍정"
        if v >= -0.15: return "중립"
        if v >= -0.45: return "잔잔한 부정"
        if v >= -0.7: return "분명한 부정"
        return "매우 강한 부정"
    # arousal/0to1
    v = max(0.0, min(1.0, value))
    if v >= 0.8: return "최고조"
    if v >= 0.6: return "고조"
    if v >= 0.4: return "보통"
    if v >= 0.2: return "차분함"
    return "거의 없음"


def _fmt_emotion(emotion_result: dict | None) -> str:
    """감정 평가 결과 dict → 짧은 한국어 요약 + 강도 라벨."""
    if not emotion_result:
        return "(감정 정보 없음)"
    valence = emotion_result.get('valence', 0.0)
    arousal = emotion_result.get('arousal', 0.0)
    labels = emotion_result.get('preliminary_labels') or []
    label_text = ", ".join(labels) if labels else "라벨 없음"
    v_lbl = _intensity_label(valence, "valence")
    a_lbl = _intensity_label(arousal, "arousal")
    return (
        f"valence={valence:.2f} ({v_lbl}), "
        f"arousal={arousal:.2f} ({a_lbl}), 라벨=[{label_text}]"
    )


def _fmt_social(social_result: dict | None) -> str:
    """사회인지 결과 dict → 짧은 한국어 요약. None 허용."""
    if not social_result:
        return "(상대 정보 없음)"
    intent = social_result.get('estimated_intent') or social_result.get('inferred_intent') or "추정 의도 없음"
    other_emo = social_result.get('estimated_emotion') or {}
    if isinstance(other_emo, dict) and other_emo:
        ov = other_emo.get('valence', 0.0)
        oa = other_emo.get('arousal', 0.0)
        emo_text = f"상대 v={ov:.2f}/a={oa:.2f}"
    else:
        emo_text = "상대 감정 미상"
    social_reward = social_result.get('social_reward')
    sr_text = f", social_reward={social_reward:.2f}" if isinstance(social_reward, (int, float)) else ""
    return f"의도={intent}; {emo_text}{sr_text}"


def _fmt_memory(memory_result: dict | None) -> str:
    """기억 인출 결과 → 상위 K개 스니펫의 짧은 줄바꿈 문자열."""
    if not memory_result:
        return "(관련 기억 없음)"
    items = memory_result.get('memories') or []
    if not items:
        return "(관련 기억 없음)"
    # 상위 3개까지만 노출 (프롬프트 길이 컨트롤)
    snippets: list[str] = []
    for item in items[:3]:
        if not isinstance(item, dict):
            continue
        content = item.get('content', '')
        importance = item.get('importance')
        if isinstance(importance, (int, float)):
            snippets.append(f"- {content} (중요도 {importance:.2f})")
        else:
            snippets.append(f"- {content}")
    return "\n".join(snippets) if snippets else "(관련 기억 없음)"


def _fmt_mood(mood: dict | None) -> str:
    """현재 기분(mood) → 짧은 한국어 요약 + 강도 라벨."""
    if not mood:
        return "(기분 정보 없음)"
    valence = mood.get('valence')
    arousal = mood.get('arousal')
    parts: list[str] = []
    if isinstance(valence, (int, float)):
        parts.append(f"valence={valence:.2f} ({_intensity_label(valence, 'valence')})")
    if isinstance(arousal, (int, float)):
        parts.append(f"arousal={arousal:.2f} ({_intensity_label(arousal, 'arousal')})")
    label = mood.get('label')
    if label:
        parts.append(f"label={label}")
    return ", ".join(parts) if parts else "(기분 정보 없음)"


_INTERNAL_STATE_LABELS_KO = {
    'reward': '보상감/동기',
    'patience': '인내·진정',
    'arousal': '각성',
    'learning': '학습·열린-사고',
    'excitation': '흥분',
    'inhibition': '억제·자제',
    'stress': '스트레스',
    'bonding': '유대감',
    'comfort': '안위',
}


def _state_descriptor(value: float, baseline: float) -> str | None:
    """state 값을 baseline 대비 정성 라벨로. baseline 근처면 None (생략)."""
    dev = value - baseline
    abs_dev = abs(dev)
    if abs_dev < 0.15:
        return None
    # 절댓값으로 강도 결정.
    if value >= 0.85: lvl = "거의 만점"
    elif value >= 0.65: lvl = "꽤 높음"
    elif value >= 0.4: lvl = "다소 높음" if dev > 0 else "다소 낮음"
    elif value >= 0.15: lvl = "낮은 편"
    else: lvl = "거의 바닥"
    direction = "↑" if dev > 0 else "↓"
    return f"{lvl}{direction}"


def _fmt_internal_state(
    internal_state: dict | None,
    baselines: dict | None,
) -> str:
    """저수준 9 파라미터 → 정성 라벨 요약. baseline 에서 큰 편차만 표시.

    spec §3.1 의 신호 상승 정밀도 손실 의도와 충돌하지 않도록, 숫자는 노출하지
    않고 정성 라벨만 노출 ("유대감: 거의 만점↑"). 캘리브레이션이 안 된 LLM 이
    감정 평가만 보고는 saturation 을 못 알아채는 정보 병목을 푼다.

    ADR-010 (layered identity vs 표현력) 참조.
    """
    if not internal_state or not baselines:
        return "(내부 상태 정보 없음)"
    parts: list[str] = []
    for key, label in _INTERNAL_STATE_LABELS_KO.items():
        v = internal_state.get(key)
        b = baselines.get(key)
        if not isinstance(v, (int, float)) or not isinstance(b, (int, float)):
            continue
        desc = _state_descriptor(float(v), float(b))
        if desc is not None:
            parts.append(f"{label} {desc}")
    if not parts:
        return "(전반 안정 — baseline 근방)"
    return "; ".join(parts)


def _fmt_recent_dialogue(recent_dialogue: list | None) -> str:
    """직전 N턴 대화 → 사람:/나: 형식의 짧은 transcript. 빈 입력은 '(첫 대화 턴)'."""
    if not recent_dialogue:
        return "(첫 대화 턴 — 직전 대화 없음)"
    lines: list[str] = []
    for entry in recent_dialogue:
        if not isinstance(entry, dict):
            continue
        u = entry.get('user', '').strip()
        a = entry.get('assistant', '').strip()
        if u:
            lines.append(f"사람: {u}")
        if a:
            lines.append(f"나: {a}")
    return "\n".join(lines) if lines else "(첫 대화 턴 — 직전 대화 없음)"


class CandidateGeneration:
    """후보 응답 생성 모듈 (큰 모델)."""

    def __init__(self, llm_client: LLMClient | None = None, n_candidates: int = 3):
        self.llm = llm_client or LLMClient()
        self.template = load_prompt('candidate_generation')
        self.n_candidates = n_candidates

    async def generate(
        self,
        emotion_result: dict,
        social_result: dict | None,
        memory_result: dict,
        self_model: dict,
        mood: dict,
        marker_signal: str,
        user_input: str,
        recent_dialogue: list | None = None,
        internal_state: dict | None = None,
        baselines: dict | None = None,
    ) -> list[dict]:
        """후보 N개 생성. 반환: [{'style': str, 'text': str}, ...].

        Args:
            recent_dialogue: 직전 N턴의 [{'user': str, 'assistant': str}, ...].
                None/빈 리스트면 "(첫 대화 턴)" 으로 렌더링.

        Raises:
            LLMError: LLM 호출 실패 또는 스키마 검증 실패. 호출부에서 fallback 처리.
        """
        emotion_summary = _fmt_emotion(emotion_result)
        social_summary = _fmt_social(social_result)
        memory_summary = _fmt_memory(memory_result)
        mood_text = _fmt_mood(mood)
        self_narrative = (self_model or {}).get('narrative', '') if isinstance(self_model, dict) else ''
        recent_dialogue_text = _fmt_recent_dialogue(recent_dialogue)
        internal_state_summary = _fmt_internal_state(internal_state, baselines)

        rendered = self.template.render(
            user_input=user_input,
            emotion_summary=emotion_summary,
            social_summary=social_summary,
            memory_summary=memory_summary,
            self_narrative=self_narrative,
            mood_text=mood_text,
            marker_signal=marker_signal,
            n_candidates=self.n_candidates,
            recent_dialogue=recent_dialogue_text,
            internal_state_summary=internal_state_summary,
        )
        messages = [
            {"role": "system", "content": _SYSTEM_MESSAGE},
            {"role": "user", "content": rendered},
        ]
        result = await self.llm.complete_json(
            messages,
            schema=CandidatesResponse,
            model_name='large_model',
        )
        return result['candidates']
