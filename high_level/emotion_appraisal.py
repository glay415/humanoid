"""① 감정 평가 — 작은 모델 LLM.

입력 + 코어어펙트 → 혼합 벡터 + reward/threat/novelty + preliminary_labels.
Scherer CPM 4단계 중 관련성/함의를 담당. 대처(메타인지)·규범(사회인지)은 다른 모듈.

설계 메모:
- system 메시지에 역할 지시(어떤 단계만 판단하는지, JSON 출력 강제)를 두고,
  user 메시지에 prompts/emotion_appraisal.txt 렌더 결과(입력값 포함)를 둔다.
  이렇게 분리하는 이유:
    1) 역할 지시는 입력에 따라 변하지 않으므로 system 으로 캐시하기 좋다.
    2) JSON-only 강제는 system 으로 두는 편이 OpenAI 권장 패턴이다.
    3) 템플릿 본문은 실제 데이터 평가에 집중하도록 user 로 둔다.
- 스키마 검증은 LLMClient.complete_json 이 EmotionAppraised 로 처리한다.
- 실패 시 LLMError 가 그대로 전파됨 → 오케스트레이터의 _emotion_fallback 이 받는다.
"""
from __future__ import annotations

from interface.schemas import EmotionAppraised
from llm.client import LLMClient
from llm.prompts import load_prompt


_SYSTEM_MESSAGE = (
    "당신은 인지 아키텍처의 '감정 평가(emotion appraisal)' 모듈이다. "
    "Scherer CPM 4단계 중 관련성(relevance)과 함의(implications)만 판단하라. "
    "대처(coping)는 메타인지, 규범(normative)은 사회인지가 담당하므로 그 판단은 절대 하지 마라. "
    "Barrett TCE의 '예측이 먼저' 원칙에 따라 코어어펙트와 입력만으로 preliminary_labels(초벌)를 만든다. "
    "출력은 오직 한 개의 JSON 객체이며, 자연어 설명·마크다운 코드펜스·추가 키를 금지한다. "
    "모든 수치 범위(valence: -1~1, arousal/reward/threat/novelty: 0~1)를 반드시 지킨다."
)


class EmotionAppraisal:
    """감정 평가 모듈 (작은 모델)."""

    def __init__(self, llm_client: LLMClient | None = None):
        self.llm = llm_client or LLMClient()
        self.template = load_prompt('emotion_appraisal')

    async def evaluate(
        self,
        user_input: str,
        raw_core_affect: dict[str, float],
        recent_memory_summary: str = "",
    ) -> dict:
        """입력 + 현재 코어어펙트 → 감정 평가 결과.

        Returns:
            EmotionAppraised 스키마와 동일한 dict (model_dump 결과).
        Raises:
            LLMError: LLM 호출 실패 또는 스키마 검증 실패. 호출부에서 fallback 처리.
        """
        rendered = self.template.render(
            user_input=user_input,
            valence=raw_core_affect.get('valence', 0.0),
            arousal=raw_core_affect.get('arousal', 0.0),
            recent_memory_summary=recent_memory_summary,
        )
        messages = [
            {"role": "system", "content": _SYSTEM_MESSAGE},
            {"role": "user", "content": rendered},
        ]
        return await self.llm.complete_json(
            messages,
            schema=EmotionAppraised,
            model_name='small_model',
        )

    async def reappraise(
        self,
        prev_result: dict,
        strategy: str,
    ) -> dict:
        """재평가 (메타인지 요청 시). 동기화 지점 내에서 수행."""
        raise NotImplementedError("Phase 5")
