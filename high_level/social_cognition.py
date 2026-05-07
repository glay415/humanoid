"""② 사회인지 — 작은 모델 LLM.

입력 + 타자모델 + 감정결과 → 상대 상태 추정 + social_reward.
Phase 5에서 LLM 평가 추가. Wave 4 단계에서는 default 반환.
"""


class SocialCognition:
    """② 사회인지 — Phase 5에서 LLM 평가 추가. Wave 4 단계에서는 default 반환."""

    async def evaluate(
        self,
        user_input: str,
        other_model: dict,
        emotion_result: dict,
    ) -> dict:
        """사회인지 평가. 반환: {person_id, estimated_emotion, estimated_intent, social_reward}.

        Wave 4 단계: orchestrator 가 의존하므로 NotImplementedError 대신 안전한 기본값 반환.
        Phase 5 에서 실제 LLM 호출로 대체.
        """
        return {
            'person_id': 'default',
            'estimated_emotion': {'valence': 0.0, 'arousal': 0.3},
            'estimated_intent': '',
            'social_reward': 0.0,
        }
