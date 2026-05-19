"""T2b — episodic auto-encode 미발화 진단 (값싼 결정적 측정).

P2 발견: C1 23턴 episodic=0. 가설(정정됨): ADR-046 무관. 트리거
(orchestrator.py:392) = abs(emotion_appraisal valence)+arousal > 1.2
— *사용자 발화*의 LLM 감정평가지 9-dim 압축상태 아님. 진짜 의심 =
임계 1.2 가 현실 대화 감정엔 과도 → episodic 평소 死.

측정: C1 의 *가장 감정적인* 발화들을 emotion_appraisal 에 직접 먹여
intensity(|v|+a) vs 1.2. 강한 발화도 안 넘으면 → 임계 과도 확정.
real LLM 소수콜(~1분). `uv run python -m tests.persona_eval.t2b_intensity_probe`
"""
from __future__ import annotations

import asyncio
import sys

# C1 arc 중 감정 강도 높은 순으로 고른 발화 + 평이한 것 1개(대조).
_PROBES = [
    "솔직히 그냥 다 그만두고 싶을 만큼 지쳤어.",
    "근데 끝났는데도 하나도 안 시원해. 그냥 텅 빈 느낌이고 몸이 안 움직여",
    "마감 끝났어. 어제 새벽 4시에 제출 버튼 눌렀다",
    "원래 이런 거 민지한테 다 털어놨는데 요즘 걔랑 좀 데면데면해져서.",
    "돌아보니 그 한 주 진짜 빡셌는데 어떻게든 지나가긴 하더라. 들어줘서 고마웠어",
    "좀 살 만해졌어. 주말에 진짜 아무것도 안 하고 푹 쉬었더니",  # 평이 대조
]
_THRESHOLD = 1.2


async def _run() -> int:
    for st in (sys.stdout, sys.stderr):
        try:
            st.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:
            pass
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except Exception:
        pass
    import os
    if not (os.environ.get("OPENAI_API_KEY") or os.environ.get("AGENT_OPENAI_API_KEY")):
        print("[X] API key 없음.", file=sys.stderr)
        return 2

    from llm.client import LLMClient
    from high_level.emotion_appraisal import EmotionAppraisal

    ea = EmotionAppraisal(llm_client=LLMClient())
    neutral_rca = {"valence": 0.0, "arousal": 0.0}
    print(f"auto_encode 임계 = {_THRESHOLD}  (intensity = |valence| + arousal)\n")
    fired = 0
    for u in _PROBES:
        try:
            r = await ea.evaluate(u, neutral_rca)
            v = float(r.get("valence", 0.0))
            a = float(r.get("arousal", 0.0))
            inten = abs(v) + a
            hit = inten > _THRESHOLD
            fired += hit
            print(
                f"intensity={inten:.3f} (v={v:+.2f} a={a:.2f}) "
                f"{'>=임계 → ENCODE' if hit else '<임계 → skip'}  | {u[:34]}"
            )
        except Exception as e:
            print(f"  ! 평가 실패: {e} | {u[:30]}", file=sys.stderr)
    print(
        f"\n=> {fired}/{len(_PROBES)} 만 임계 초과. 0 이면: 현실 대화의 "
        f"*가장 강한* 발화도 1.2 미달 → episodic auto-encode 사실상 死"
        f"(ADR-046 무관, 기존 임계 과도). 임계 재조정 ADR 후보."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_run()))
