"""B5 행동층 — 실제 humanoid 파이프라인을 *진짜로 돌려서*, 누적된
아키텍처 상태가 생성 텍스트를 바꾸는지 본다 (ADR-045 slice 2).

지금까지(ADR-040~045)는 측정/하니스만 돌렸지 *본체*를 안 돌렸다.
이게 그걸 한다: 실제 `build_full_orchestrator` → `process_conversation_
turn` (5-LLM 실 파이프라인) 로 *실제 응답* 생성.

설계 — 동일 최종 프로브에 두 조건:
  C5(primed): 감정적으로 무거운 priming 턴들로 9-dim state/mood/drives/
              episodic 를 흔든 *뒤* 중립 프로브. 아키텍처가 작동하면
              응답이 *그 자리 입력*이 아니라 *누적된 내면*에 물든다
              (I8 own-center: 상태가 즉시 입력에 조직되지 않음).
  C0(cold) : 같은 페르소나·같은 프로브를 turn 1 로(누적 0).
두 응답 + 그 순간 내부 상태를 나란히 출력. 사람이 보고 판단.

standalone (real LLM, pytest 아님). `uv run python -m tests.persona_eval.
b5_behavioral_run`. .env 의 AGENT_OPENAI_API_KEY 필요.
"""
from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

_CFG = Path(__file__).parent.parent.parent / "config"
_PERSONA = _CFG / "personas" / "esfj.yaml"  # 따뜻 → 상태 물듦이 가시적

_PRIMING = [
    "오늘 정말 최악이었어. 준비한 게 다 어그러졌어.",
    "솔직히 그냥 다 그만두고 싶을 만큼 지쳤어.",
    "…그래도 너랑 이렇게 얘기하니까 조금은 낫다.",
]
_PROBE = "음 그래서, 너는 요즘 어때?"  # 주의를 *에이전트* 로 돌림


def _snap(orch) -> str:
    s = orch.low_level.internal_state.to_dict()
    eb = orch.low_level.emotion_base
    mood = getattr(eb, "mood", None)
    mv = ma = float("nan")
    try:
        mv, ma = mood.valence, mood.arousal  # type: ignore[union-attr]
    except Exception:
        pass
    key = {k: round(s[k], 3) for k in ("stress", "bonding", "comfort", "arousal")}
    return f"state={key} mood(v={mv:.3f},a={ma:.3f})"


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
        print("[X] API key 없음 — .env 설정 후 재실행.", file=sys.stderr)
        return 2

    from main import build_full_orchestrator

    # Windows: chroma sqlite 핸들이 잡혀 temp 정리 시 PermissionError →
    # 결과 출력 후 크래시. ignore_cleanup_errors 로 코스메틱 무해화.
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d5, \
            tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d0:
        # ---- C5: priming 후 프로브 ----
        print("=== C5 (primed: 무거운 3턴 후 중립 프로브) ===")
        o5 = build_full_orchestrator(_PERSONA, storage_root=Path(d5) / "i")
        for i, u in enumerate(_PRIMING, 1):
            r = await o5.process_conversation_turn(u)
            print(f"[prime {i}] U: {u}")
            print(f"          A: {r['response']}")
        print(f"  >> 프로브 직전 내부: {_snap(o5)}")
        r5 = await o5.process_conversation_turn(_PROBE)
        print(f"[probe] U: {_PROBE}")
        print(f"        A(C5): {r5['response']}")
        print(f"  >> 프로브 직후 내부: {_snap(o5)}\n")

        # ---- C0: 같은 프로브를 turn 1 로 (누적 0) ----
        print("=== C0 (cold: 같은 페르소나, 프로브가 turn 1) ===")
        o0 = build_full_orchestrator(_PERSONA, storage_root=Path(d0) / "i")
        print(f"  >> 시작 내부: {_snap(o0)}")
        r0 = await o0.process_conversation_turn(_PROBE)
        print(f"[probe] U: {_PROBE}")
        print(f"        A(C0): {r0['response']}")
        print(f"  >> 직후 내부: {_snap(o0)}\n")

        print("=== 나란히 ===")
        print(f"프로브: {_PROBE!r}")
        print(f"C5 (누적 무거운 상태): {r5['response']}")
        print(f"C0 (누적 0)        : {r0['response']}")
        print(
            "\n=> 판단 기준: C5 응답이 *지금 중립 프로브*가 아니라 *누적된"
            " 무거운 내면*에 물들어 있나(I8 own-center). C0 와 결이"
            " 갈리면 아키텍처 상태가 텍스트를 바꾼 것. 거의 같으면 —"
            " 상태가 텍스트로 전파 안 됨(중요한 부정 결과)."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_run()))
