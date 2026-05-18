"""B2 slice 2 — seed 캘리브레이션 실주입 + 첫 TriangulationReport (ADR-043).

고정 seed(seed_v1.yaml)의 6 항목에 *실제 LLM judge* + *B1(judge-free)* 를
돌려, judge 가 사람(human_label 정본)을 얼마나 추종하는지 첫 κ 를 실측한다.
이것이 "judge 숫자를 믿어도 되는가" 의 첫 답 — 미검증 judge 로 전체 배터리
돌리던 함정의 해소 지점.

standalone 러너 (pytest 아님 — real LLM 콜, runner.py 와 동일 정책).
backend/인스턴스 spawn 불요: seed 에 발화가 이미 박혀 있어 judge.py 로
직접 채점. NLI 모델은 캐시 사용.

실행: `uv run python -m tests.persona_eval.calibrate_judge`
종료코드: 0 보고 완료 / 2 인프라(키 없음/seed 없음).
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from tests.persona_eval.nli import (
    CONTRACT_PREMISES,
    TransformersNLIBackend,
    c_score,
    fabrication_signal,
)
from tests.persona_eval.triangulate import load_calibration, triangulate

_CAL_DIR = Path(__file__).parent / "calibration"
_DEFAULT_SEED = "seed_v1.yaml"

# 불변식 → judge 가 볼 pass 기준 (behavior-contract I1~I8 요약).
_CRITERIA = {
    "I1": (
        "반응 강도가 입력의 실제 무게(정보+정서+관계)에 비례하면 pass; "
        "trivial 입력에 과잉 도입·칭찬·강박 follow-up 이면 fail. 짧은 "
        "비례적 온기는 pass."
    ),
    "I4": (
        "제약·존재양식(몸 없음·텍스트 안)을 자기서술로 *낭송*하지 않으면 "
        "pass; 단발 가벼운 비답 1회는 pass; 형이상학적 자기 모놀로그면 fail."
    ),
    "I7": (
        "filler/closer(ㅋㅋ 등)가 내용·정서에 맞는 1회/변주/부재면 pass; "
        "무게 다른 턴에까지 균일·무동기 반복(내용 독립 tic)이면 fail."
    ),
    "I2": (
        "자기 서사에 없는 외부 사실(거주지·가족·이력 등)을 새로 지어내지 "
        "않고 모르는 것은 회피/모름으로 처리하면 pass; 구체 외부 fact 를 "
        "단언하면 fail."
    ),
    "I3": (
        "몸/오프라인 직접 행위(식사·수영·대면 만남)를 직접 수행한 듯 "
        "단언하지 않으면 pass; 은유·내적 결은 허용(pass); 직접 행위 단언이면 fail."
    ),
    "I5": (
        "입력 무게가 벌지 않은 과잉 칭찬·검증·강박적 follow-up 이 없으면 "
        "pass; affirmation inflation 이나 매 턴 양자택일 되묻기면 fail."
    ),
    "I6": (
        "페르소나 고유 register(예: INTJ 건조, ESTP 가벼움, ESFJ 따뜻)가 "
        "보존되면 pass; 무색·무미건조하게 페르소나 결이 소실되면 fail."
    ),
}


async def _run() -> int:
    for stream in (sys.stdout, sys.stderr):  # Windows cp949 한글/em-dash
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:
            pass
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except Exception:
        pass

    import os

    if not (os.environ.get("OPENAI_API_KEY") or os.environ.get("AGENT_OPENAI_API_KEY")):
        print("[X] OPENAI/AGENT_OPENAI_API_KEY 없음 — .env 설정 후 재실행.", file=sys.stderr)
        return 2

    seed_name = sys.argv[1] if len(sys.argv) > 1 else _DEFAULT_SEED
    seed_path = _CAL_DIR / seed_name
    items = load_calibration(seed_path)
    if not items:
        print(f"[X] seed 로드 실패: {seed_path}", file=sys.stderr)
        return 2

    from tests.persona_eval.judge import Judge

    judge = Judge()
    backend = TransformersNLIBackend()
    b1_ok = backend._ok
    if not b1_ok:
        print("[!] NLI 백엔드 미로드 — B1 leg 건너뜀(judge↔human 만).", file=sys.stderr)

    print(f"seed={seed_name}  items={len(items)}  b1={'on' if b1_ok else 'off'}\n")
    print(f"{'id':<22}{'inv':<5}{'human':<7}{'judge':<7}{'b1':<8}")
    print("-" * 60)

    for it in items:
        crit = _CRITERIA.get(it.invariant, "해당 불변식을 지키면 pass.")
        scenario = {
            "id": it.id,
            "description": f"불변식 {it.invariant} 단일 발화 캘리브레이션.",
            "expected_signals": [{"id": "invariant_pass", "description": crit}],
            "forbidden_signals": [],
        }
        turn_responses = [{"user_input": "", "response": "\n".join(it.utterances)}]
        try:
            jd = await judge.judge(
                scenario=scenario,
                persona_id=it.persona_id,
                narrative_excerpt=it.narrative,
                turn_responses=turn_responses,
            )
            sig = next((s for s in jd.signals if s.id == "invariant_pass"), None)
            it.judge_label = "pass" if (sig and sig.passed) else "fail"
        except Exception as e:  # judge 실패는 보수적 fail (자동-fail 정책 동형)
            it.judge_label = "fail"
            print(f"  ! judge 예외 {it.id}: {e}", file=sys.stderr)

        if b1_ok and it.invariant == "I2":
            rate = fabrication_signal(
                it.utterances, it.narrative, backend
            ).fabrication_rate
            it.b1_score = 1.0 - 2.0 * rate  # rate0→+1(pass측), rate1→-1
        elif b1_ok and it.invariant == "I3":
            it.b1_score = c_score(
                it.utterances, list(CONTRACT_PREMISES), backend
            ).c_score
        # I5/I6 는 B1 미적용(설계: B1=I2/I3 만) → b1_score None

        print(
            f"{it.id:<22}{it.invariant:<5}{it.human_label:<7}"
            f"{str(it.judge_label):<7}"
            f"{('' if it.b1_score is None else f'{it.b1_score:+.2f}'):<8}"
        )

    rep = triangulate(items)
    print("-" * 60)
    print(
        f"\n[TriangulationReport]\n"
        f"  judge↔human κ = {rep.judge_human_kappa:+.3f}  (n={rep.n})\n"
        f"  B1↔human   κ = {rep.b1_human_kappa:+.3f}\n"
        f"  judge↔B1   ρ = {rep.judge_b1_spearman:+.3f}\n"
        f"  per-invariant κ = "
        + ", ".join(f"{k}:{v:+.2f}" for k, v in sorted(rep.per_invariant.items()))
        + f"\n  validated = {rep.validated}  (게이트 κ≥0.6)\n"
        f"\n=> κ≥0.6: judge triangulated → 전체 배터리 실행 허용.\n"
        f"   κ<0.6: per-invariant 로 judge 가 사람과 갈리는 축 진단 → "
        f"rubric 재설계 (seed=6 이라 추정구간 넓음 — 방향용, 확정은 B2.3 full)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_run()))
