"""ADR-037 L1 — soft-quality critic (생성 후 비동기 검수 mini LLM).

L2 (response_guardrails) 가 hard 위반을 deterministic 하게 잡는다면, 이
critic 은 *결의 품질* 을 본다 — RLHF sycophancy (검증·감탄 인플레이션 /
강박 follow-up), 존재양식 낭송 tic, 비례 깨짐 (반응 ∝ 입력 무게), persona
색 소실. behavior contract (ADR-036 proportionality / anti-sycophancy +
ADR-037 anti-recitation) 를 soft 축에서 강제한다.

draft 가 깨끗하면 ``needs_rewrite=False`` 통과. soft 인공물이 있으면 *그
인공물만* 고친 짧은 in-persona 재작성을 돌려준다 (새 내용 추가 X, 의미·
페르소나 보존, 과잉발화였으면 더 짧게).

성능: small_model + reasoning_effort='low'. 호출자가 응답 stream 완료 후
background 로 돌린다 (turn latency 영향 0 — 다음 턴 반영 or 즉시 교체).

FAIL-OPEN: LLMError / JSON parse / shape 오류 → 무엇이든
``CriticResult(needs_rewrite=False, rewritten=None, reason='critic_unavailable')``.
``review()`` 는 *절대* raise 하지 않는다 — 925-green / production 턴을
critic 버그로 막지 않는다 (ADR-035 affect_translator 와 같은 철학,
단 여기선 호출자 fallback 이 아니라 모듈 내부 fail-open).
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from llm.client import LLMClient
from llm.prompts import load_prompt


@dataclass
class CriticResult:
    """L1 soft-quality 검수 결과.

    Attributes:
        needs_rewrite: True = soft 인공물 감지, ``rewritten`` 사용 권고.
        rewritten: 인공물만 고친 in-persona 재작성. ``needs_rewrite`` 가
            False 면 항상 None.
        reason: 한 줄 근거. fail-open 시 ``'critic_unavailable'``.
    """

    needs_rewrite: bool
    rewritten: str | None
    reason: str


_SYSTEM_MESSAGE = (
    "당신은 응답 *결 검수기*. 사용자에게 보이지 않는 내부 모듈. 생성된 draft"
    " 가 sycophancy (검증·감탄 인플레이션 / 강박 follow-up), 존재양식 낭송"
    " tic, 비례 깨짐 (반응 ∝ 입력 무게), 페르소나 색 소실 — 의 soft 인공물을"
    " 갖는지 판정. 깨끗하면 손대지 말 것. 인공물이 있으면 *그것만* 고친 짧은"
    " in-persona 재작성 (새 내용·정보 추가 금지, 의미·페르소나 보존, 과잉"
    " 발화였으면 더 짧게). JSON 만 출력."
)


class ResponseCritic:
    """soft-quality 검수 mini LLM 1 콜. review() 는 never-raise (fail-open)."""

    DEFAULT_MODEL_NAME = 'small_model'

    def __init__(self, llm_client: LLMClient | None = None):
        self.llm = llm_client or LLMClient()
        self.template = load_prompt('response_critic')

    async def review(
        self,
        draft: str,
        *,
        user_input: str,
        self_narrative: str,
        affect_description: str | None = None,
        risk_signals: dict | None = None,
        recent_assistant_turns: list[str] | None = None,
        model_name: str | None = None,
    ) -> CriticResult:
        """draft 의 soft 품질을 검수. NEVER raises (fail-open).

        Args:
            draft: 검수 대상 생성 응답.
            user_input: 이번 턴 사용자 발화 (비례 판단 기준).
            self_narrative: 페르소나 narrative (persona-tint 기준).
            affect_description: 상태 정성 묘사 (옵셔널).
            risk_signals: 리스크 신호 dict (옵셔널).
            recent_assistant_turns: ADR-038 — 직전 어시스턴트 발화들.
                주어지면 critic 이 I7 무말버릇 (cross-turn filler 반복)
                도 함께 판정. None/빈 리스트면 종전(ADR-037) 동작과
                바이트 동일 (back-compat).
            model_name: LLM tier. default ``small_model``.

        Returns:
            CriticResult. 깨끗하면 ``needs_rewrite=False, rewritten=None``.
            *어떤* 오류라도 fail-open → ``needs_rewrite=False,
            rewritten=None, reason='critic_unavailable'``.
        """
        text = (draft or '').strip()
        if not text:
            return CriticResult(False, None, 'empty_draft')
        try:
            rendered = self.template.render(
                draft=text,
                user_input=(user_input or '').strip(),
                self_narrative=(self_narrative or '').strip(),
                affect_description=(affect_description or '미확립').strip()
                or '미확립',
                risk_signals=self._fmt_risk(risk_signals),
                recent_assistant_turns=self._fmt_recent_turns(
                    recent_assistant_turns
                ),
            )
            messages = [
                {"role": "system", "content": _SYSTEM_MESSAGE},
                {"role": "user", "content": rendered},
            ]
            out = await self.llm.complete(
                messages,
                model_name=model_name or self.DEFAULT_MODEL_NAME,
                reasoning_effort='low',
            )
            return self._parse(out)
        except Exception:
            # LLMError / render KeyError / 무엇이든 — fail-open.
            return CriticResult(False, None, 'critic_unavailable')

    # ------------------------------------------------------------------
    @staticmethod
    def _fmt_risk(risk_signals: dict | None) -> str:
        if not risk_signals:
            return '없음'
        try:
            return json.dumps(risk_signals, ensure_ascii=False)
        except Exception:
            return '없음'

    @staticmethod
    def _fmt_recent_turns(recent_assistant_turns: list[str] | None) -> str:
        """최근 어시스턴트 턴들을 프롬프트 슬롯 문자열로. 비면 ''.

        None/빈 리스트면 빈 문자열 → 프롬프트의 I7 블록이 스스로
        "건너뜀" → ADR-037 동작과 의미상 동일 (back-compat).
        """
        try:
            turns = [
                str(t).strip()
                for t in (recent_assistant_turns or [])
                if t and str(t).strip()
            ]
            if not turns:
                return ''
            return '\n'.join(
                f'- (턴 -{len(turns) - i}) {t}'
                for i, t in enumerate(turns)
            )
        except Exception:
            return ''

    @staticmethod
    def _parse(raw: str) -> CriticResult:
        try:
            data = json.loads((raw or '').strip())
        except Exception:
            return CriticResult(False, None, 'critic_unavailable')
        if not isinstance(data, dict):
            return CriticResult(False, None, 'critic_unavailable')

        needs = bool(data.get('needs_rewrite', False))
        reason = str(data.get('reason', '') or '').strip() or (
            'needs_rewrite' if needs else 'clean'
        )
        rewritten_raw = data.get('rewritten')
        rewritten = (
            str(rewritten_raw).strip()
            if rewritten_raw not in (None, '', 'null')
            else None
        )
        if needs and not rewritten:
            # 재작성을 약속했는데 비어 있으면 안전하게 통과 (원본 유지).
            return CriticResult(False, None, 'critic_unavailable')
        if not needs:
            rewritten = None
        return CriticResult(needs, rewritten, reason)
