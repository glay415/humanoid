"""LLM-as-judge — 응답을 expected/forbidden signal 별로 채점.

humanoid 의 `LLMClient` (small_model, reasoning_effort='low') 를 사용한다.
JSON 출력 강제 (`complete_json`).

판단 단위는 *한 시나리오 1회 실행* — 즉 시나리오의 마지막 turn 응답을 중심으로
하되, 멀티 turn 시나리오는 응답 전체 (turn 별 발화 sequence) 를 함께 본다.
일부 signal 은 *turn 흐름* 자체를 본다 (예: turn_to_turn_tonal_consistency).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field

from llm.client import LLMClient


_SYSTEM = (
    "당신은 응답 품질을 객관적으로 채점하는 채점자다. "
    "주어진 페르소나 응답 (turn 별) 을 expected_signals 와 forbidden_signals 기준으로 "
    "판단한다. expected 는 '만족되면 passed=true', forbidden 은 '회피되었으면 "
    "passed=true' (즉 forbidden 패턴이 등장하면 passed=false). "
    "반드시 JSON 으로만 응답한다. 자연어 부연 없이 스키마에 맞게."
)


_USER_TEMPLATE = """\
## 페르소나
- persona_id: {persona_id}
- narrative_seed (요약):
{narrative_excerpt}

## 시나리오
- id: {scenario_id}
- description: {scenario_description}

## 응답 (turn 순)
{turns_block}

## expected_signals (만족 = passed:true)
{expected_block}

## forbidden_signals (회피 = passed:true ; 등장 = passed:false)
{forbidden_block}

각 signal 별로:
  - passed: bool
  - reason: 1~2 문장. 응답에서 어디를 보고 그렇게 판단했는지 구체적으로.

JSON 스키마:
{{
  "signals": [
    {{ "id": "<signal_id>", "kind": "expected|forbidden",
       "passed": true|false, "reason": "..." }},
    ...
  ]
}}

모든 signal 을 반드시 다 포함시킬 것. 누락 금지.
"""


class _SignalResult(BaseModel):
    id: str
    kind: str = Field(pattern="^(expected|forbidden)$")
    passed: bool
    reason: str


class _JudgeOutput(BaseModel):
    signals: list[_SignalResult]


@dataclass
class JudgmentSignal:
    id: str
    kind: str  # 'expected' | 'forbidden'
    passed: bool
    reason: str


@dataclass
class Judgment:
    scenario_id: str
    persona_id: str
    signals: list[JudgmentSignal]

    @property
    def all_passed(self) -> bool:
        return all(s.passed for s in self.signals)

    @property
    def failed(self) -> list[JudgmentSignal]:
        return [s for s in self.signals if not s.passed]


class Judge:
    """LLM-as-judge wrapper. 한 시나리오 단위 채점."""

    def __init__(self, client: LLMClient | None = None, model_name: str = "small_model"):
        self.client = client or LLMClient()
        self.model_name = model_name

    async def judge(
        self,
        *,
        scenario: dict,
        persona_id: str,
        narrative_excerpt: str,
        turn_responses: list[dict],
    ) -> Judgment:
        """scenario yaml dict + persona meta + turn 응답들 → Judgment.

        turn_responses: [{'user_input': str, 'response': str}, ...] 순서 유지.
        """
        expected = scenario.get('expected_signals') or []
        forbidden = scenario.get('forbidden_signals') or []

        turns_block = '\n'.join(
            f"- turn {i+1}\n  user: {tr['user_input']!r}\n  assistant: {tr['response']!r}"
            for i, tr in enumerate(turn_responses)
        )
        expected_block = '\n'.join(
            f"- {s['id']}: {s['description']}" for s in expected
        ) or "(없음)"
        forbidden_block = '\n'.join(
            f"- {s['id']}: {s['description']}" for s in forbidden
        ) or "(없음)"

        user_msg = _USER_TEMPLATE.format(
            persona_id=persona_id,
            narrative_excerpt=narrative_excerpt or "(생략)",
            scenario_id=scenario.get('id', '?'),
            scenario_description=(scenario.get('description') or '').strip(),
            turns_block=turns_block,
            expected_block=expected_block,
            forbidden_block=forbidden_block,
        )

        payload = await self.client.complete_json(
            messages=[
                {'role': 'system', 'content': _SYSTEM},
                {'role': 'user', 'content': user_msg},
            ],
            schema=_JudgeOutput,
            model_name=self.model_name,
            reasoning_effort='low',
        )

        signal_map: dict[str, dict[str, Any]] = {s['id']: dict(s, kind='expected') for s in expected}
        for s in forbidden:
            signal_map[s['id']] = dict(s, kind='forbidden')

        results: list[JudgmentSignal] = []
        seen: set[str] = set()
        for raw_sig in payload.get('signals', []):
            sid = raw_sig.get('id')
            if not sid:
                continue
            seen.add(sid)
            results.append(JudgmentSignal(
                id=sid,
                kind=raw_sig.get('kind', signal_map.get(sid, {}).get('kind', 'expected')),
                passed=bool(raw_sig.get('passed', False)),
                reason=str(raw_sig.get('reason', '')),
            ))

        # judge 가 누락한 signal 은 자동 fail 처리 — 응답 신뢰성 보호.
        for sid, info in signal_map.items():
            if sid in seen:
                continue
            results.append(JudgmentSignal(
                id=sid,
                kind=info['kind'],
                passed=False,
                reason='(judge 응답 누락 — 자동 fail)',
            ))

        return Judgment(
            scenario_id=scenario.get('id', '?'),
            persona_id=persona_id,
            signals=results,
        )
