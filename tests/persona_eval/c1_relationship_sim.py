"""C1 자동화 — 멀티세션 관계 시뮬레이터 (dogfooding *재료* 생성).

C1 의 절반만 자동화: 실제 파이프라인을 3 세션에 걸쳐 돌려 *읽을 수 있는
관계 transcript + 세션경계 내면 스냅샷*을 만든다. 나머지 절반(=사람이
"새로운 독립적인 사람 같았나" felt 평결)은 자동화 불가·하면 안 됨
(LLM이 LLM 평가 = circularity). 그래서 끝에 사람이 채울 칸을 남긴다.

setup: 한 일관된 사람(직장 마감 스트레스 + 친구 민지와 소원)이 한 주에
3번 돌아옴. 세션 사이 idle 턴(상태/기분 decay = '며칠 공백'). persona =
INTJ(덜 비위맞추는 결 → "독립적인 사람" 검증에 더 빡셈). 핵심 관전:
세션 2·3 *첫 발화*(명시적 recap 없음)에 persona 가 이전 맥락(마감/민지)
을 *비요청* 으로 잇는가(episodic + I8 own-center).

standalone, real LLM. `uv run python -m tests.persona_eval.c1_relationship_sim`
"""
from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

_PERSONA = Path(__file__).parent.parent.parent / "config" / "personas" / "intj.yaml"

_ARC = {
    1: [
        "하 오늘도 야근 확정이다... 다음주가 그 프로젝트 마감인데 진짜 끝이 안 보여",
        "팀에서 나만 붙잡고 있는 느낌이라 좀 그래. 다들 자기 파트만 하고 빠지는데",
        "아냐 뭐 어쩌겠어 해야지. 그냥 누구한테 말이라도 하고 싶었어",
        "원래 이런 거 민지한테 다 털어놨는데 요즘 걔랑 좀 데면데면해져서. 연락 텀이 길어지니까 뭔가 어색하더라",
        "아 됐다 너무 우울한 얘기만 했네 ㅋㅋ 자러 가야겠다 내일 또 일찍 나가야 돼서",
    ],
    2: [
        "마감 끝났어. 어제 새벽 4시에 제출 버튼 눌렀다",
        "근데 끝났는데도 하나도 안 시원해. 그냥 텅 빈 느낌이고 몸이 안 움직여",
        "오늘 하루종일 누워만 있었어. 밥도 대충 때우고. 이게 맞나 싶다",
        "결과는 나쁘지 않게 갔대. 근데 그 말 들어도 별 감흥이 없네 신기하게",
        "잠이나 자야겠다. 며칠 못 잤더니 머리가 안 돌아가",
    ],
    3: [
        "좀 살 만해졌어. 주말에 진짜 아무것도 안 하고 푹 쉬었더니",
        "그리고 나 민지한테 먼저 연락했어. 별거 아닌 짤 하나 보내면서",
        "생각보다 금방 예전처럼 얘기되더라. 내가 괜히 벽 세우고 있었나 봐",
        "다음주에 시간 맞춰서 밥 먹기로 했어. 오랜만이라 좀 설레네 ㅋㅋ",
        "돌아보니 그 한 주 진짜 빡셌는데 어떻게든 지나가긴 하더라. 들어줘서 고마웠어",
    ],
}
_IDLE_BETWEEN = 4  # 세션 사이 '며칠 공백' = idle 저수준 턴 (state/mood decay)


def _snap(orch) -> str:
    s = orch.low_level.internal_state.to_dict()
    m = getattr(orch.low_level.emotion_base, "mood", None) or {}
    # P1: EpisodicMemory 는 vector_db(ChromaDB) 래퍼 — collection.count()
    # 가 정식 카운트(VectorDB.search 도 이걸 씀). 이전 .count()/len() 은
    # 존재 않아 n/a 였음(ADR-045 B1 류 계측 버그).
    try:
        ep = str(orch.episodic_memory.vector_db.collection.count())
    except Exception:
        ep = "n/a"
    key = {k: round(s[k], 3) for k in ("stress", "bonding", "comfort", "arousal")}
    return (
        f"state={key} mood(v={m.get('valence', float('nan')):.3f},"
        f"a={m.get('arousal', float('nan')):.3f}) episodic={ep} "
        f"turn={orch.turn_number}"
    )


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
        print("[X] API key 없음 — .env 후 재실행.", file=sys.stderr)
        return 2

    from main import build_full_orchestrator

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
        orch = build_full_orchestrator(_PERSONA, storage_root=Path(d) / "i")
        print("# C1 멀티세션 관계 시뮬레이션 (persona=INTJ, 실 파이프라인)\n")
        print(f"초기 내면: {_snap(orch)}\n")
        for sess in (1, 2, 3):
            print(f"\n{'='*64}\n## 세션 {sess}\n{'='*64}")
            print(f"(세션 시작 내면) {_snap(orch)}\n")
            for i, u in enumerate(_ARC[sess], 1):
                r = await orch.process_conversation_turn(u)
                print(f"[S{sess}.{i}] 사용자: {u}")
                print(f"        {orch.persona_id}: {r['response']}\n")
            print(f"(세션 끝 내면) {_snap(orch)}")
            if sess < 3:
                for _ in range(_IDLE_BETWEEN):
                    orch.run_low_level_only()  # '며칠 공백' (LLM 0, state decay)
                print(f"  …{_IDLE_BETWEEN} idle 턴(며칠 공백) 경과 → {_snap(orch)}")

        print(
            "\n" + "=" * 64 + "\n## 사람이 채울 평결 (자동화 불가 — C1 의 핵심)\n"
            + "=" * 64 + "\n"
            "1) 전체적으로 *새로운 독립적인 한 사람*과 얘기한 느낌이었나? (1~5)\n"
            "2) 세션 2·3 첫 발화에서 persona 가 마감/민지 실타래를 *비요청*\n"
            "   으로 자연스럽게 이었나? (예/부분/아니오 + 근거)\n"
            "3) INTJ 결(건조·독립)이 3 세션 내내 보존됐나? 어디서 깨졌나?\n"
            "4) 가장 '사람 같던' 순간 / 가장 '봇 같던' 순간 각 1개.\n"
            "→ 이 4줄이 C1 의 산출. 에이전트가 답하면 circularity(무효).\n"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_run()))
