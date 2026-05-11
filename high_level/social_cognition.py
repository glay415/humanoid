"""② 사회인지 — 작은 모델 LLM.

입력 + 타자모델 + 감정결과 → 상대 상태 추정 + social_reward.
Scherer CPM 4단계 중 **규범(normative significance)** 만 담당.
관련성/함의는 ① 감정 평가, 대처는 메타인지가 처리한다.

설계 메모:
- LLM 호출 실패(LLMError) 시 Wave 4 의 fallback 기본값을 그대로 반환한다.
  오케스트레이터의 e2e 흐름이 이 fallback shape에 의존하므로 보수적으로 유지.
- 입력 dict 들은 missing key 에 안전하게 동작해야 한다 → _fmt_* 헬퍼가 흡수.
"""
from __future__ import annotations

from interface.schemas import SocialCognitionResult
from llm.client import LLMClient, LLMError
from llm.prompts import load_prompt


_SYSTEM_MESSAGE = (
    "당신은 인지 아키텍처의 '사회인지(social cognition)' 모듈이다. "
    "Scherer CPM 4단계 중 규범(normative significance)만 판단하라. "
    "관련성/함의는 감정 평가, 대처는 메타인지가 담당하므로 그 판단은 절대 하지 마라. "
    "이 발화가 사회·문화적 규범에 얼마나 부합하는지, 상대의 감정/의도는 무엇으로 추정되는지, "
    "그리고 우리에게 보상적인지(social_reward)를 종합한다. "
    "출력은 오직 한 개의 JSON 객체이며, 자연어 설명·마크다운 코드펜스·추가 키를 금지한다. "
    "수치 범위(valence: -1~1, arousal/social_reward: 0~1)를 반드시 지킨다."
)


_FALLBACK_RESULT: dict = {
    'person_id': 'default',
    'estimated_emotion': {'valence': 0.0, 'arousal': 0.3},
    'estimated_intent': '',
    'social_reward': 0.0,
}


class SocialCognition:
    """사회인지 모듈 (작은 모델). Wave 4 fallback shape 보존."""

    def __init__(self, llm_client: LLMClient | None = None):
        self.llm = llm_client or LLMClient()
        self.template = load_prompt('social_cognition')

    async def evaluate(
        self,
        user_input: str,
        other_model: dict,
        emotion_result: dict,
    ) -> dict:
        """사회인지 평가. 반환: {person_id, estimated_emotion, estimated_intent, social_reward}.

        LLMError 가 나면 Wave 4 기본값(_FALLBACK_RESULT) 으로 폴백한다.
        오케스트레이터의 e2e 가 이 dict shape 에 의존하므로 함부로 바꾸지 말 것.
        """
        emotion_summary = self._fmt_emotion(emotion_result)
        other_model_summary = self._fmt_other_model(other_model)
        rendered = self.template.render(
            user_input=user_input,
            emotion_summary=emotion_summary,
            other_model_summary=other_model_summary,
        )
        messages = [
            {"role": "system", "content": _SYSTEM_MESSAGE},
            {"role": "user", "content": rendered},
        ]
        try:
            # social_cognition 은 의도/감정 추정 분류 정도 — reasoning 거의 불필요.
            # minimal 로 강제해서 latency 7~10s → 1~3s.
            return await self.llm.complete_json(
                messages,
                schema=SocialCognitionResult,
                model_name='small_model',
                reasoning_effort='minimal',
            )
        except LLMError:
            # Wave 4 fallback — orchestrator 의 기본 흐름을 보존.
            return dict(_FALLBACK_RESULT) | {
                'estimated_emotion': dict(_FALLBACK_RESULT['estimated_emotion']),
            }

    # ------------------------------------------------------------------
    # 헬퍼 — pure functions, missing fields 에 안전
    # ------------------------------------------------------------------

    @staticmethod
    def _fmt_emotion(emotion_result: dict) -> str:
        """감정 평가 결과 → 짧은 한국어 요약 문자열.

        emotion_result 는 EmotionAppraised dict 형태를 기대하지만
        키 누락에도 안전하게 동작한다.
        """
        if not emotion_result:
            return "(감정 정보 없음)"
        valence = emotion_result.get('valence', 0.0)
        arousal = emotion_result.get('arousal', 0.0)
        labels = emotion_result.get('preliminary_labels') or []
        dims = emotion_result.get('experience_dimensions') or {}
        reward = dims.get('reward', 0.0) if isinstance(dims, dict) else 0.0
        threat = dims.get('threat', 0.0) if isinstance(dims, dict) else 0.0
        novelty = dims.get('novelty', 0.0) if isinstance(dims, dict) else 0.0
        labels_text = ", ".join(str(x) for x in labels) if labels else "(없음)"
        return (
            f"valence={valence:.2f}, arousal={arousal:.2f}, "
            f"라벨=[{labels_text}], "
            f"reward={reward:.2f}, threat={threat:.2f}, novelty={novelty:.2f}"
        )

    @staticmethod
    def _fmt_other_model(other_model: dict) -> str:
        """타자모델 dict → 짧은 한국어 요약 문자열.

        other_model 은 storage.OtherModel.to_dict() 결과 형태를 기대.
        비어 있으면 "(상대 정보 없음)" 반환.
        """
        if not other_model:
            return "(상대 정보 없음)"
        narrative = other_model.get('narrative') or ''
        observation_count = other_model.get('observation_count', 0)
        relationship_stage = other_model.get('relationship_stage', 'initial')
        threat_streak = other_model.get('threat_streak', 0)
        narrative_text = narrative if narrative else "(서술 없음)"
        return (
            f"서술={narrative_text}; "
            f"관찰횟수={observation_count}; "
            f"관계단계={relationship_stage}; "
            f"위협연속={threat_streak}"
        )
