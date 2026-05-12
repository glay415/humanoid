"""비동기 자기 분석(introspection) — 매 turn 끝에 background 로 호출되는 일기 쓰기.

매 turn 의 사용자 stream 이 끝난 후 fire-and-forget 으로 호출된다. 페르소나가
*자기* 의 1인칭 시점에서 직전 몇 턴 동안의 내부 변화를 짧게 일기로 적는다.
결과는 IntrospectionLogger 가 instances/<id>/introspection.jsonl 로 누적.

설계 메모:
- 사용자 turn 의 latency 에 영향을 주지 않는다 — orchestrator 가
  asyncio.create_task() 로 띄우고 결과를 await 하지 않는다.
- 실패는 호출부에서 swallow — 일기 쓰기 실패가 본 시스템을 멈추면 안 됨.
- small_model + reasoning_effort='low' — 짧고 가벼운 콜.
- pydantic 검증을 LLMClient.complete_json 이 IntrospectionResult 로 처리.
  실패 시 LLMError 가 그대로 전파됨 → 호출부 (orchestrator._run_introspection_safe)
  가 swallow.
"""
from __future__ import annotations

from storage.log_schemas import IntrospectionResult
from llm.client import LLMClient
from llm.prompts import load_prompt


_SYSTEM_MESSAGE = (
    "당신은 인지 아키텍처의 '내성(introspection)' 모듈이다. "
    "지금 보고 있는 페르소나의 직전 몇 턴 동안의 내부 변화를, "
    "페르소나 본인의 1인칭 시점에서 짧은 일기처럼 적는다. "
    "변수명·수치·시스템 용어 (stress, valence, arousal, 마커, 0.45 같은 숫자) 를 "
    "절대 입에 담지 마라. 몸과 마음의 느낌으로 환원해 적는다. "
    "분석가 시점 ('페르소나는…') 이 아니라 '나는…' 으로 쓴다. "
    "출력은 오직 한 개의 JSON 객체이며, 자연어 설명·마크다운 코드펜스·추가 키를 금지한다."
)


class Introspection:
    """페르소나 일기 쓰기 모듈 (작은 모델, background)."""

    def __init__(self, llm_client: LLMClient | None = None):
        self.llm = llm_client or LLMClient()
        self.template = load_prompt('introspection')

    async def analyze(
        self,
        *,
        persona_narrative: str,
        recent_turns_summary: str,
        recent_dialogue_text: str,
        marker_changes: str,
        current_state: dict,
        current_mood: dict,
    ) -> dict:
        """직전 N 턴의 흐름 + 현재 상태 → 페르소나 일기.

        Args:
            persona_narrative: self_model.narrative (페르소나 톤의 정체성 서술).
            recent_turns_summary: 직전 5턴 동안의 state/mood/drives delta 요약
                (호출부에서 평탄화한 텍스트). 시스템 용어는 prompt 내에서 자연어로 환원.
            recent_dialogue_text: dialogue_buffer 의 최근 (user, assistant) 텍스트.
            marker_changes: 이번 턴에 형성/감쇠된 마커 요약 (1줄당 1개, 평문).
            current_state: 9-dim internal state dict (분석 시점).
            current_mood: mood dict (분석 시점).

        Returns:
            IntrospectionResult.model_dump() — 4 필드 dict.

        Raises:
            LLMError: LLM 호출/검증 실패. 호출부에서 swallow.
        """
        rendered = self.template.render(
            persona_narrative=persona_narrative or '(아직 정체감이 또렷하지 않다)',
            recent_turns_summary=recent_turns_summary or '(직전 턴 기록이 부족하다)',
            recent_dialogue_text=recent_dialogue_text or '(최근 대화 없음)',
            marker_changes=marker_changes or '(이번 턴에 두드러진 마커 변화는 없었다)',
            current_state=_format_dict_inline(current_state),
            current_mood=_format_dict_inline(current_mood),
        )
        messages = [
            {"role": "system", "content": _SYSTEM_MESSAGE},
            {"role": "user", "content": rendered},
        ]
        return await self.llm.complete_json(
            messages,
            schema=IntrospectionResult,
            model_name='small_model',
            reasoning_effort='low',
        )


def _format_dict_inline(d: dict) -> str:
    """dict[str, float] 를 짧은 inline 표현으로. LLM prompt 가독성 ↑."""
    if not d:
        return '(비어 있음)'
    parts: list[str] = []
    for k, v in d.items():
        try:
            parts.append(f"{k}={float(v):.2f}")
        except (TypeError, ValueError):
            parts.append(f"{k}={v}")
    return ', '.join(parts)


__all__ = ['Introspection']
