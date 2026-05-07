"""② 사회인지 — 작은 모델 LLM.

입력 + 타자모델 + 감정결과 → 상대 상태 추정 + social_reward.
Phase 5에서 구현.
"""


class SocialCognition:
    """사회인지 모듈 (작은 모델)."""

    async def evaluate(
        self,
        user_input: str,
        other_model: dict,
        emotion_result: dict,
    ) -> dict:
        """사회인지 평가. 반환: {person_id, estimated_emotion, estimated_intent, social_reward}."""
        raise NotImplementedError("Phase 5")
