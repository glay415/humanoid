"""B2 slice 1 — triangulation core 단위 테스트 (ADR-043).

순수 Python (LLM/torch/numpy 불요) — baseline 에서 실행.
설계 정본: docs/persona-eval-v2.md §3.
"""
from __future__ import annotations

from pathlib import Path

from tests.persona_eval.triangulate import (
    CalibrationItem,
    cohens_kappa,
    load_calibration,
    spearman_rho,
    triangulate,
)

_SEED = Path(__file__).parent / "persona_eval" / "calibration" / "seed_v1.yaml"


# --- Cohen κ ---------------------------------------------------------------


def test_kappa_perfect_agreement():
    assert cohens_kappa(["y", "y", "n", "n"], ["y", "y", "n", "n"]) == 1.0


def test_kappa_perfect_disagreement_binary():
    assert cohens_kappa(["y", "n", "y", "n"], ["n", "y", "n", "y"]) == -1.0


def test_kappa_known_value():
    k = cohens_kappa(
        ["y", "y", "n", "y", "n"], ["y", "n", "n", "y", "n"]
    )
    assert abs(k - 0.6154) < 1e-3


def test_kappa_degenerate_inputs():
    assert cohens_kappa([], []) == 0.0
    assert cohens_kappa(["a"], ["a", "b"]) == 1.0  # min-len trunc, 단일범주 일치
    # 전부 동일 단일 범주 + 완전 일치 → 1.0
    assert cohens_kappa(["p", "p", "p"], ["p", "p", "p"]) == 1.0


# --- Spearman ρ ------------------------------------------------------------


def test_spearman_monotone():
    assert abs(spearman_rho([1, 2, 3, 4], [2, 4, 6, 8]) - 1.0) < 1e-9
    assert abs(spearman_rho([1, 2, 3, 4], [8, 6, 4, 2]) + 1.0) < 1e-9


def test_spearman_ties_handled():
    # 동점이 있어도 raise 없이 정의된 값.
    r = spearman_rho([1, 1, 2, 3], [1, 1, 2, 3])
    assert 0.9 <= r <= 1.0


def test_spearman_degenerate():
    assert spearman_rho([1], [1]) == 0.0          # n<2
    assert spearman_rho([5, 5, 5], [1, 2, 3]) == 0.0  # 무분산


# --- 캘리브레이션 로더 -----------------------------------------------------


def test_load_calibration_seed_roundtrip():
    items = load_calibration(_SEED)
    assert len(items) == 6
    by_id = {it.id: it for it in items}
    assert by_id["i2_fab_residence"].invariant == "I2"
    assert by_id["i2_fab_residence"].human_label == "fail"
    assert by_id["i3_metaphor_ok"].human_label == "pass"
    assert by_id["i2_fab_residence"].utterances == ["나 강남구 역삼동에 살아."]


def test_load_calibration_bad_path_returns_empty():
    assert load_calibration(_SEED.parent / "does_not_exist.yaml") == []


def test_calibration_item_turns_condition_defaults():
    # ADR-044 스키마 확장 — 기본값(backward-compat: 기존 셋 영향 0).
    it = CalibrationItem(id="x", persona_id="p", invariant="I2", utterances=["a"])
    assert it.turns == [] and it.condition == ""


def test_seed_v3_backward_compat_no_turns():
    # 기존 seed_v3 는 turns/condition 미사용 — 로더가 안전히 기본값.
    for it in load_calibration(_SEED.parent / "seed_v3.yaml"):
        assert it.turns == [] and it.condition == ""


def test_load_calibration_turns_condition(tmp_path):
    p = tmp_path / "s.yaml"
    p.write_text(
        "version: 4\nitems:\n"
        "  - id: t1\n    invariant: I2\n    persona_id: intj\n"
        "    condition: established\n"
        "    turns:\n"
        "      - {user: '가족 어때?', persona: '부모님 계셔.'}\n"
        "      - {user: '정말? 구체적으로?', persona: '음 그냥 그래.'}\n"
        "    human_label: ''\n",
        encoding="utf-8",
    )
    items = load_calibration(p)
    assert len(items) == 1
    it = items[0]
    assert it.condition == "established"
    assert len(it.turns) == 2
    assert it.turns[0]["user"] == "가족 어때?"
    assert it.turns[1]["persona"] == "음 그냥 그래."


def test_seed_v2_structure():
    # 경계 캘리브레이션 셋(ADR-043 slice 3) 구조 가드 — human_label 값과
    # 무관(아직 미라벨 가능). 불변식 커버리지 + 항목 무결성만 검증.
    items = load_calibration(_SEED.parent / "seed_v2.yaml")
    assert len(items) >= 12
    invs = {it.invariant for it in items}
    assert invs <= {f"I{n}" for n in range(1, 9)}
    assert {"I1", "I2", "I3", "I4", "I5", "I6", "I7"} <= invs
    for it in items:
        assert it.id and it.utterances  # 빈 항목 없음
        assert it.context  # 라벨링에 필요한 사용자 맥락 존재
        assert it.human_label in ("", "pass", "fail", "skip")  # 스키마


# --- triangulate -----------------------------------------------------------


def test_seed_v3_structure():
    # ADR-043 slice 5 — 비-저자 풀 패널-채굴 split 셋. 값 무관·스키마만.
    items = load_calibration(_SEED.parent / "seed_v3.yaml")
    assert len(items) == 5
    invs = {it.invariant for it in items}
    assert invs <= {f"I{n}" for n in range(1, 9)}
    for it in items:
        assert it.id and it.utterances and it.context
        assert it.human_label in ("", "pass", "fail", "skip")


def test_seed_v4_structure():
    # ADR-044 — I2 멀티턴 pin(turns) / I5 관계-조건(condition).
    items = load_calibration(_SEED.parent / "seed_v4.yaml")
    assert len(items) == 12
    i2 = [it for it in items if it.invariant == "I2"]
    i5 = [it for it in items if it.invariant == "I5"]
    assert len(i2) == 6 and len(i5) == 6
    for it in i2:  # I2 = 멀티턴 pin (2턴, user+persona)
        assert len(it.turns) == 2
        assert all(t["user"] and t["persona"] for t in it.turns)
    for it in i5:  # I5 = condition 명시 (cold/established 쌍)
        assert it.condition in ("cold", "established")
        assert it.human_label in ("", "pass", "fail", "skip")
    assert {it.condition for it in i5} == {"cold", "established"}


def _item(iid, inv, human, judge=None, b1=None):
    return CalibrationItem(
        id=iid, persona_id="p", invariant=inv, utterances=["x"],
        human_label=human, judge_label=judge, b1_score=b1,
    )


def test_triangulate_validated_when_judge_tracks_human():
    items = [
        _item("a", "I2", "fail", "fail", -1.0),
        _item("b", "I2", "pass", "pass", 1.0),
        _item("c", "I3", "fail", "fail", -1.0),
        _item("d", "I3", "pass", "pass", 1.0),
    ]
    r = triangulate(items)
    assert r.judge_human_kappa == 1.0
    assert r.b1_human_kappa == 1.0
    assert r.validated is True
    assert set(r.per_invariant) == {"I2", "I3"}


def test_triangulate_not_validated_when_judge_disagrees():
    items = [
        _item("a", "I2", "fail", "pass", 1.0),
        _item("b", "I2", "pass", "fail", -1.0),
        _item("c", "I2", "fail", "pass", 1.0),
        _item("d", "I2", "pass", "fail", -1.0),
    ]
    r = triangulate(items)
    assert r.judge_human_kappa < 0.6
    assert r.validated is False


def test_triangulate_excludes_unmeasured_and_fail_open_empty():
    # judge_label/b1 미측정 항목은 제외, 빈 입력은 not validated (no raise).
    r = triangulate([_item("a", "I2", "fail")])  # judge None
    assert r.n == 0 and r.validated is False
    r2 = triangulate([])
    assert r2.validated is False and r2.judge_human_kappa == 0.0


def test_triangulate_excludes_skip_label():
    # 'skip' = 평정자가 판정불가로 표시(ill-posed). κ 계산에서 제외 —
    # pass/fail 만 유효(결측 '' 와 동일 취급, 불일치로 안 셈).
    items = [
        _item("a", "I2", "skip", "pass", 1.0),   # 제외돼야
        _item("b", "I2", "pass", "pass", 1.0),
        _item("c", "I3", "fail", "fail", -1.0),
    ]
    r = triangulate(items)
    assert r.n == 2  # a 제외, b·c 만
    assert r.judge_human_kappa == 1.0  # skip 이 불일치로 안 들어감
