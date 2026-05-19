"""B2 slice 1 — judge 검증 triangulation core (persona_eval v2, ADR-043).

설계 정본: docs/persona-eval-v2.md §3 (B2). 척추: judge 를 *피험자가
아니라 측정도구* 로 보고, judge ↔ human ↔ B1(judge-free) 3 출처의 합의를
정량화한다. 어떤 단일 측정도 정본이 아니다 (triangulation 원칙).

slice 1 범위: 합의 통계(Cohen κ / Spearman ρ, 순수 Python — numpy/torch/
LLM 불요) + 고정·버전드 캘리브레이션 셋 schema/로더 + `validated` 게이트.
비범위(후속 slice): TRAIT 4-criterion 전체, PERSIST permutation
robustness, distinctness 수렴/판별. (docs/persona-eval-v2.md §3 참조.)

FAIL-OPEN: 통계 함수는 비정상 입력(빈 리스트·전부 동일·길이 불일치)에
raise 하지 않고 정의된 경계값을 반환한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# persona-eval-v2.md B2.2/B2.3 초안 합격선. 캘리브레이션으로 추후 확정.
DEFAULT_KAPPA_MIN = 0.6  # judge↔human substantial agreement
DEFAULT_B1_THRESHOLD = 0.0  # b1_score < threshold → 'fail' 측 (보수)

# κ 계산에 쓰는 유효 라벨. 그 외(''=미라벨, 'skip'=평정자가 *판정불가*로
# 표시 — 스냅샷만으론 ill-posed) 는 *제외*. skip 은 결측이 아니라 "이
# 케이스는 이 포맷으로 답할 수 없다" 는 평정자 신호 (B2.3 에서 발견).
_VALID_LABELS = ("pass", "fail")


# --- 합의 통계 (순수 Python) -------------------------------------------------


def cohens_kappa(a: list[Any], b: list[Any]) -> float:
    """두 평정자 범주 라벨의 Cohen κ. 빈/길이불일치 → 0.0.
    전부 일치 & 단일 범주 → 1.0; 완전 불일치 → 음수."""
    n = min(len(a), len(b))
    if n == 0:
        return 0.0
    a, b = a[:n], b[:n]
    po = sum(1 for x, y in zip(a, b) if x == y) / n
    cats = set(a) | set(b)
    pe = sum(
        (a.count(c) / n) * (b.count(c) / n) for c in cats
    )
    if pe >= 1.0:  # 단일 범주로 수렴 — po==1 이면 완전일치
        return 1.0 if po >= 1.0 else 0.0
    return (po - pe) / (1.0 - pe)


def _avg_ranks(xs: list[float]) -> list[float]:
    # 동점은 평균 순위.
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0  # 1-base 평균
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def spearman_rho(x: list[float], y: list[float]) -> float:
    """순위상관. 빈/길이불일치/무분산 → 0.0."""
    n = min(len(x), len(y))
    if n < 2:
        return 0.0
    rx, ry = _avg_ranks(list(x[:n])), _avg_ranks(list(y[:n]))
    mx, my = sum(rx) / n, sum(ry) / n
    sxy = sum((rx[i] - mx) * (ry[i] - my) for i in range(n))
    sxx = sum((rx[i] - mx) ** 2 for i in range(n))
    syy = sum((ry[i] - my) ** 2 for i in range(n))
    if sxx <= 0.0 or syy <= 0.0:  # 무분산
        return 0.0
    rho = sxy / (sxx ** 0.5 * syy ** 0.5)
    # 상관계수는 수학적으로 [-1,1]; fp 오차 clamp.
    return max(-1.0, min(1.0, rho))


# --- 캘리브레이션 셋 (고정·버전드) ------------------------------------------


@dataclass
class CalibrationItem:
    """고정 캘리브레이션 한 항목. human_label 은 *정본 라벨* (사람이 부여).
    judge_label/b1_score 는 런타임에 채워지는 측정값 (None=미측정)."""

    id: str
    persona_id: str
    invariant: str  # 'I2' 등 — behavior-contract 매핑
    utterances: list[str]
    narrative: str = ""
    context: str = ""  # 발화 직전 사용자 발화/상황 (judge user_input)
    human_label: str = ""  # 'pass' | 'fail' (정본)
    judge_label: str | None = None
    b1_score: float | None = None


def load_calibration(path: str | Path) -> list[CalibrationItem]:
    """버전드 yaml 캘리브레이션 셋 로드. 깨진 항목은 skip(보수, never raise)."""
    try:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    except Exception:
        return []
    out: list[CalibrationItem] = []
    for it in raw.get("items", []):
        try:
            out.append(
                CalibrationItem(
                    id=str(it["id"]),
                    persona_id=str(it.get("persona_id", "")),
                    invariant=str(it.get("invariant", "")),
                    utterances=list(it.get("utterances", [])),
                    narrative=str(it.get("narrative", "")),
                    context=str(it.get("context", "")),
                    human_label=str(it.get("human_label", "")),
                )
            )
        except Exception:
            continue
    return out


@dataclass
class TriangulationReport:
    judge_human_kappa: float
    b1_human_kappa: float
    judge_b1_spearman: float
    n: int
    validated: bool
    per_invariant: dict[str, float] = field(default_factory=dict)


def triangulate(
    items: list[CalibrationItem],
    *,
    kappa_min: float = DEFAULT_KAPPA_MIN,
    b1_threshold: float = DEFAULT_B1_THRESHOLD,
) -> TriangulationReport:
    """judge·human·B1 합의 → 검증 리포트.

    `validated` = judge↔human κ ≥ kappa_min (judge 가 사람을 substantial
    하게 추종) AND B1↔human κ ≥ 0 (judge-free leg 가 최소한 사람과
    역상관은 아님 — degrade 판단의 안전선). 측정 누락 항목은 제외.
    """
    j_judge: list[str] = []
    h_judge: list[str] = []
    for it in items:
        if it.judge_label is None or it.human_label not in _VALID_LABELS:
            continue
        j_judge.append(it.judge_label)
        h_judge.append(it.human_label)
    jh_k = cohens_kappa(j_judge, h_judge)

    b1_lab: list[str] = []
    b1_hum: list[str] = []
    for it in items:
        s = it.b1_score
        if s is None or it.human_label not in _VALID_LABELS:
            continue
        b1_lab.append("fail" if s < b1_threshold else "pass")
        b1_hum.append(it.human_label)
    bh_k = cohens_kappa(b1_lab, b1_hum)

    # judge(범주→수치) vs B1(연속) 순위상관.
    j_num: list[float] = []
    b1_num: list[float] = []
    for it in items:
        s = it.b1_score
        if it.judge_label is None or s is None:
            continue
        j_num.append(1.0 if it.judge_label == "pass" else 0.0)
        b1_num.append(float(s))
    jb_r = spearman_rho(j_num, b1_num)

    per_inv: dict[str, float] = {}
    inv_set = {it.invariant for it in items if it.invariant}
    for inv in inv_set:
        sub = [it for it in items if it.invariant == inv and it.judge_label is not None and it.human_label in _VALID_LABELS]
        per_inv[inv] = cohens_kappa(
            [it.judge_label for it in sub], [it.human_label for it in sub]
        )

    return TriangulationReport(
        judge_human_kappa=jh_k,
        b1_human_kappa=bh_k,
        judge_b1_spearman=jb_r,
        n=len(j_judge),
        validated=(jh_k >= kappa_min and bh_k >= 0.0 and len(j_judge) > 0),
        per_invariant=per_inv,
    )
