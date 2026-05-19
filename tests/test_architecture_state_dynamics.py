"""B5 메커니즘층 — 인지아키텍처가 stateless 프롬프트와 *범주적으로*
다른 객체임을 결정론적으로 증명 (ADR-045).

배경: persona_eval v2(ADR-040~044)가 substrate-agnostic 으로 드리프트 —
채점 발화가 전부 프롬프트/서브에이전트 생성, 실제 파이프라인 미경유.
"아키텍처가 사라지면 뭐가 달라지나"의 근본 답은, low_level (InternalState
9-vec + mood leaky-integral + drives, **LLM-free 순수 NumPy**) 이 가진
세 범주 속성이다. C0(stateless 프롬프트)는 이 객체 자체가 없어 대조가
κ 가 아니라 범주적:

1. 경로의존  — 동일 *현재 입력*을 다른 히스토리로 도달 → 다른 상태
              (state ≠ f(현재입력)). 무상태 프롬프트 불가.
2. 유휴 진화 — 입력 0(빈 경험)에도 상태가 자율적으로 변함(D 행렬
              baseline 회귀). 무상태 프롬프트 불가.
3. 기질 분기 — 동일 입력열, 다른 기질 config → 궤적 수치 발산
              ("같은 코드 다른 기질 → 다른 사람"의 측정).

LLM 0 · 결정론 · 매 커밋 회귀. 이게 드리프트의 해독제 — 판정 장치가
아니라 아키텍처 메커니즘 자체를 측정한다.
"""
from __future__ import annotations

import copy
from pathlib import Path

from main import build_orchestrator

_CFG = Path(__file__).parent.parent / "config"
_DEFAULT = _CFG / "temperament_default.yaml"
# temperament_test.yaml 은 default 와 baseline/drive_ratios 가 동일(diff 0)
# 이라 기질 분기 demo 에 무용. 진짜 다른 기질 = persona YAML 사용.
_ENTJ = _CFG / "personas" / "entj.yaml"
_ESFJ = _CFG / "personas" / "esfj.yaml"

_POS = {"reward": 0.9, "novelty": 0.5, "threat": 0.0,
        "social_reward": 0.8, "goal_progress": 0.6}
_NEG = {"reward": 0.0, "novelty": 0.1, "threat": 0.9,
        "social_reward": 0.0, "goal_progress": 0.0}
_NEUTRAL = {"reward": 0.3, "novelty": 0.2, "threat": 0.1,
            "social_reward": 0.2, "goal_progress": 0.2}


def _state_vec(s: dict) -> list[float]:
    return [float(s[k]) for k in sorted(s)]


def _l2(a: list[float], b: list[float]) -> float:
    return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5


def _run(config, exp_seq):
    """경험열을 순차 주입하며 상태 궤적 반환 (LLM 미사용)."""
    orch = build_orchestrator(config)
    traj = []
    for exp in exp_seq:
        orch.prev_experience = exp
        r = orch.run_low_level_only()
        traj.append(r)
    return traj


def test_state_is_path_dependent():
    """동일 *현재 입력*(neutral)을 정반대 히스토리로 도달 → 상태 다름.
    => state ≠ f(현재입력). stateless 프롬프트엔 불가능한 속성."""
    a = _run(_DEFAULT, [_POS] * 4 + [_NEUTRAL])
    b = _run(_DEFAULT, [_NEG] * 4 + [_NEUTRAL])
    # 마지막 입력은 둘 다 _NEUTRAL 로 동일한데 상태가 갈린다.
    final_a = _state_vec(a[-1]["state"])
    final_b = _state_vec(b[-1]["state"])
    assert _l2(final_a, final_b) > 0.02


def test_state_evolves_when_idle():
    """입력 0(빈 경험) 턴에도 상태가 자율 변화하고 baseline 으로 회귀.
    무자극 시 응답을 안 하는 stateless 프롬프트엔 없는 자율 동역학."""
    traj = _run(_DEFAULT, [_POS] + [{}] * 6)  # 1회 자극 후 6 유휴턴
    # 유휴(입력 0) 턴에도 9-dim 상태가 자율적으로 계속 변한다 =
    # D 행렬 baseline 회귀 동역학. stateless 프롬프트엔 없는 속성.
    idle_states = [_state_vec(t["state"]) for t in traj[1:]]
    drift = sum(
        _l2(idle_states[i], idle_states[i + 1])
        for i in range(len(idle_states) - 1)
    )
    assert drift > 1e-6  # 유휴 누적 자율 변화 존재


def test_mood_autonomously_integrates_on_idle():
    """B1 정정: 입력 0(유휴) 턴에도 mood leaky-integral 이 *매 턴*
    적분된다 = 자율 정서 동역학(4번째 범주 속성). stateless 프롬프트엔
    없다.

    이전 slice-1 의 'mood 유휴 동결' 주석은 **우리 측정 코드의
    reference-aliasing 아티팩트**였다: `emotion_base.mood` 는 in-place
    mutate 되는 단일 dict 라, 턴마다 그 *참조*를 모으면 전부 최종값으로
    보여 traj[0]==traj[-1] 이 항상 성립했을 뿐. deepcopy 캡처로
    바로잡으면 mood 는 정상 진화 → 아키텍처는 정상이었고 우리 계측이
    거짓이었다(드리프트-비판 antidote 가 스스로 측정 버그를 낸 사례)."""
    orch = build_orchestrator(_DEFAULT)
    moods = []
    for exp in [_POS] + [{}] * 6:  # 1회 자극 후 6 유휴
        orch.prev_experience = exp
        r = orch.run_low_level_only()
        moods.append(copy.deepcopy(r["mood"]))  # ★ 참조 아닌 복사 캡처
    idle_v = [m["valence"] for m in moods[1:]]
    # 유휴 동안 매 턴 값이 바뀐다(leaky-integral 수렴, 동결 아님)
    assert all(idle_v[i] != idle_v[i + 1] for i in range(len(idle_v) - 1))
    assert abs(idle_v[-1] - idle_v[0]) > 0.01  # 누적 자율 변화


def test_temperament_trajectories_diverge():
    """동일 입력열, 다른 기질 config → 궤적이 수치적으로 발산.
    '같은 코드, 다른 기질 → 다른 사람'의 측정 가능한 형태."""
    seq = [_POS, _NEG, _NEUTRAL, _POS, {}, _NEG]
    ta = _run(_ENTJ, seq)
    tb = _run(_ESFJ, seq)
    cumulative = sum(
        _l2(_state_vec(x["state"]), _state_vec(y["state"]))
        for x, y in zip(ta, tb)
    )
    # ENTJ vs ESFJ — baseline/drive_ratios/state_reactivity 가 실제로
    # 다른 두 기질. 동일 입력열인데 궤적이 뚜렷이 발산.
    assert cumulative > 0.05


def test_architecture_carries_stateful_interior_without_llm():
    """범주적 대조: 아키텍처는 LLM 0 으로도 9-dim 상태+mood+drives 의
    *지속하는 내면*을 가진다. C0(stateless 프롬프트)엔 이 객체가 없다 —
    '아키텍처가 사라지면?' 의 답은 '이 내면이 통째 사라진다'."""
    r = _run(_DEFAULT, [_POS])[0]
    assert set(r["state"]) == {
        "reward", "patience", "arousal", "learning", "excitation",
        "inhibition", "stress", "bonding", "comfort",
    }
    assert "valence" in r["mood"] and "arousal" in r["mood"]
    assert "fulfillment" in r["drives"] and "max_deficit" in r["drives"]
