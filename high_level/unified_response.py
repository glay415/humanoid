"""ADR-012 — Unified single-call stream response.

기존 emotion → candidate_generation → judge_finalize.decide → stream_text
직렬 4 콜 (~26s) 을 단일 stream LLM 콜로 단축. 사용자에게 첫 토큰 ~1s 안 도착.
ChatGPT 같은 token streaming UX.

trade-off: emotion_appraisal / tone_evaluation / marker_match selection 같은
다층 cognitive 분석을 응답 prompt 안에 통합 — 별도 LLM 콜 없이 한 번에 처리.
대신 emotion_result / tone_eval 등은 응답 후 background analysis 로 갱신.

모듈 사용:
  unified = UnifiedResponse(llm_client)
  async for token in unified.stream(
      user_input=..., self_narrative=..., recent_dialogue_text=..., ...
  ):
      ... emit to SSE response_chunk ...
"""
from __future__ import annotations

from llm.client import LLMClient
from llm.prompts import load_prompt


_SYSTEM_MESSAGE = (
    "당신은 인지 아키텍처의 '통합 응답' 모듈로 호출되었으나, 사용자에게 노출되는 "
    "응답 텍스트 안에서는 [페르소나] 에 해당하는 한 사람이다. AI / 챗봇 / "
    "어시스턴트 / 언어모델이 아니다. 사용자가 메타 질문을 해도 사람으로서 "
    "자연스럽게 답한다. 출력은 응답 본문 평문만 — JSON / 마크다운 / 코드펜스 / "
    "따옴표 / 메타 라벨 금지. 응답 길이·완결성은 *현재 state + 페르소나 결* 의 "
    "함수 — 항상 매끈한 한두 문장이 아니다. 짧은 응답·미완결·침묵도 자연 결."
)


def _compute_response_form_hint(
    raw_valence: float,
    raw_arousal: float,
    internal_state_summary: str,
    metacog_resource: float,
    internal_state: dict | None = None,
) -> str:
    """ADR-033 part C — state → 응답 length/form 추천.

    state 의 함수로 응답 *form* (길이·완결성·침묵 허용) 가이드 생성. prompt 에
    별도 변수로 주입돼 LLM 이 1~3 문장 default 가 아닌 *state-conditional* length
    를 따라가게.

    ADR-033 fix (2026-05-14): internal_state dict 도 직접 참조 — 사용자가
    debug/state 로 stress 강제 직후 raw_core_affect 가 *직전 turn 값* 인 경우에도
    9-dim 으로부터 짜증/피로 신호 직접 도출. summary 텍스트 매칭에만 의존하던
    이전 정책의 한계 fix.

    분류 정책:
      - 강한 부정 + 높은 arousal (짜증/분노) → 짧고 단정 (한 단어~한 문장).
      - 강한 부정 + 낮은 arousal (우울/피로) → 짧고 미완결, 침묵 OK.
      - 강한 긍정 + 높은 arousal (흥분/활기) → 길어지거나 옆가지로 새는 결.
      - 메타인지 자원 낮음 → 단정 안 함, "..." 같은 비-응답 응답 OK.
      - 9-dim 직접 분류:
        * stress > 0.7 + inhibition < 0.3 → 짜증/조급 (짧고 단정).
        * stress > 0.7 + inhibition > 0.6 → 억눌린 짜증 (짧고 단단, 미세).
        * stress > 0.6 + (patience < 0.3 or arousal > 0.6) → 짧음 쪽.
      - 기타 (중립) → state 안의 키워드 (스트레스/피로/억제) 로 미세 조정.
    """
    summary_lower = (internal_state_summary or '').lower()
    # 스트레스/억제/피곤 키워드가 summary 에 있으면 짧음 쪽.
    fatigue_signal = any(k in summary_lower for k in ('스트레스 높', '억제 높', '피로'))

    # 메타인지 자원 낮음 (가장 강한 단축 신호).
    if metacog_resource < 0.3:
        return (
            "응답이 자연스럽게 짧아지는 결. 단정 어려움. 한 단어 ('...', '음...') "
            "또는 미완결 응답 (말 끊김, 답 자체 회피) 도 valid."
        )

    # ADR-033 fix — 9-dim 직접 분류. raw_core_affect 가 stale 한 경우 보호.
    if isinstance(internal_state, dict):
        stress = float(internal_state.get('stress', 0.0))
        inhibition = float(internal_state.get('inhibition', 0.0))
        patience = float(internal_state.get('patience', 0.5))
        arousal_dim = float(internal_state.get('arousal', 0.0))
        # 짜증/조급 — stress 매우 높음 + 억제 낮음 (욕구를 못 누름).
        if stress > 0.7 and inhibition < 0.3:
            return (
                "응답이 짧고 단정/조급한 결. 한 문장 이내. 톤은 짜증·날카로움이 묻은 "
                "색채. 친절한 호응어 ('와줘서 반갑다', '오 좋다') 절대 어울리지 않음."
            )
        # 억눌린 짜증 — stress 높음 + 억제 높음 (속에서 부글거리지만 표면 단단).
        if stress > 0.7 and inhibition > 0.6:
            return (
                "응답이 짧고 단단한 결. 한두 단어 또는 짧은 단정. 표면 정돈됐지만 "
                "*따뜻함 없는* 톤. 호응어 없이 사실만."
            )
        # 일반 피로/억제 — 응답 짧아지는 경향.
        if stress > 0.6 and (patience < 0.3 or arousal_dim > 0.6):
            return "응답이 짧고 단조로운 결. 평소의 호응어·미소 표시는 옅어짐."

    # raw_core_affect 기반 분류 (legacy 경로).
    if raw_valence < -0.5 and raw_arousal > 0.6:
        return "응답이 짧고 단정한 결. 한 문장 이내. 톤은 거리감/짜증의 색채."
    if raw_valence < -0.4 and raw_arousal < 0.4:
        return (
            "응답이 짧고 미완결로 흐르는 결. 한 단어 또는 짧은 한 문장. "
            "답이 잘 안 나오는 *침묵의 짧음* — 거짓 활기 X."
        )
    if raw_valence > 0.5 and raw_arousal > 0.6:
        return (
            "응답이 길어지거나 옆가지로 새는 결. 두세 문장 자연스럽게, 호응이 "
            "즉흥적으로 묻음."
        )
    if fatigue_signal:
        return "응답이 평소보다 짧아지는 결. 한 문장 이내가 자연."

    # 중립 — 길이 제약 없음, 페르소나 결에 맡김.
    return "응답 길이는 자유 — 페르소나의 결로부터 자연스럽게."


class UnifiedResponse:
    """단일 stream LLM 콜로 모든 cognitive context 를 응답으로 통합."""

    def __init__(self, llm_client: LLMClient | None = None):
        self.llm = llm_client or LLMClient()
        self.template = load_prompt('unified_response')

    async def stream(
        self,
        *,
        user_input: str,
        self_narrative: str,
        recent_dialogue_text: str,
        mood_text: str,
        raw_valence: float,
        raw_arousal: float,
        internal_state_summary: str,
        marker_signal: str,
        memory_summary: str,
        metacog_resource: float = 1.0,
        internal_state: dict | None = None,
    ):
        """async generator — plain text 토큰을 그대로 yield.

        stream_model (gpt-5.5 + reasoning_effort='none') 으로 non-reasoning
        mode 즉시 stream. 첫 토큰 ~500ms~1s.
        """
        # metacog 자원의 정성 라벨 (prompt 에서 LLM 에 색채 신호 주는 용도).
        if metacog_resource >= 0.7:
            metacog_label = "충분 — 자기 확신 안정"
        elif metacog_resource >= 0.4:
            metacog_label = "일상 — 약간 흔들림 있음"
        else:
            metacog_label = "약함 — 자기 의문 일렁임"

        # ADR-033 part C — state → 응답 form 추천. prompt 에 별도 변수로 주입.
        # internal_state dict 도 함께 전달해 9-dim 직접 분류 가능 (raw_core_affect
        # 가 stale 한 경우에도 stress/inhibition 으로부터 즉시 짜증 신호 도출).
        form_hint = _compute_response_form_hint(
            raw_valence=raw_valence,
            raw_arousal=raw_arousal,
            internal_state_summary=internal_state_summary or '',
            metacog_resource=metacog_resource,
            internal_state=internal_state,
        )

        rendered = self.template.render(
            user_input=user_input,
            self_narrative=self_narrative or "(자기 서사 미확립)",
            recent_dialogue=recent_dialogue_text or "(첫 대화 턴 — 직전 대화 없음)",
            mood_text=mood_text,
            raw_valence=raw_valence,
            raw_arousal=raw_arousal,
            internal_state_summary=internal_state_summary or "(매질 정보 미확립)",
            marker_signal=marker_signal or "(없음)",
            memory_summary=memory_summary or "(특별히 떠오르는 기억 없음)",
            metacog_resource=metacog_resource,
            metacog_resource_label=metacog_label,
            response_form_hint=form_hint,
        )
        messages = [
            {"role": "system", "content": _SYSTEM_MESSAGE},
            {"role": "user", "content": rendered},
        ]
        async for chunk in self.llm.complete_streaming(
            messages,
            model_name='stream_model',  # non-reasoning, stream 즉시
        ):
            yield chunk
