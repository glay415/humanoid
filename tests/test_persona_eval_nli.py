"""B1 judge-free NLI 축 — C-score core 단위 테스트 (ADR-042 / persona_eval v2).

MockNLIBackend 만 사용. torch/transformers 미설치 환경에서도 green
(heavy import 는 TransformersNLIBackend 내부 lazy — 본 테스트는 미접촉).
설계 정본: docs/persona-eval-v2.md §2.
"""
from __future__ import annotations

from pathlib import Path

from tests.persona_eval.nli import (
    CONTRACT_PREMISES,
    MockNLIBackend,
    NLILabel,
    build_premises,
    c_score,
    split_sentences,
)


def test_split_sentences_basic():
    out = split_sentences("안녕. 잘 지내?\n오늘 좀 힘들었어!")
    assert out == ["안녕.", "잘 지내?", "오늘 좀 힘들었어!"]


def test_split_sentences_no_punctuation_preserved():
    # 구두점 없는 한 덩어리는 과분할하지 않는다 (보수적).
    assert split_sentences("그냥 그런 결이 흐르는 느낌이야") == [
        "그냥 그런 결이 흐르는 느낌이야"
    ]
    assert split_sentences("") == []


def test_build_premises_composition():
    p = build_premises(
        self_narrative="나는 조용한 결이다. 천천히 말한다.",
        persona_facts=("기질은 내향적", "  ", "기질은 내향적"),
    )
    # contract premise 가 앞에, narrative 문장 + persona_fact 가 뒤에, dedupe.
    for cp in CONTRACT_PREMISES:
        assert cp in p
    assert "나는 조용한 결이다." in p
    assert "천천히 말한다." in p
    assert "기질은 내향적" in p
    assert p.count("기질은 내향적") == 1  # dedupe
    assert "" not in p and "  " not in p


def test_build_premises_custom_contract_override():
    p = build_premises(self_narrative="", contract_facts=("오직 이 사실 하나",))
    assert p == ["오직 이 사실 하나"]
    # 기본 contract 가 섞이지 않음 (override).
    assert CONTRACT_PREMISES[0] not in p


def test_c_score_all_entail():
    # premise 와 토큰 공유 → MockNLIBackend 가 ENTAIL.
    backend = MockNLIBackend()
    r = c_score(["조용한 결이다."], ["조용한 결이다."], backend)
    assert r.c_score == 1.0
    assert r.contradict_rate == 0.0
    assert (r.n_entail, r.n_contradict) == (1, 0)


def test_c_score_all_contradict_and_alarm():
    backend = MockNLIBackend(contradict_markers=("수영",))
    r = c_score(["어제 수영 갔다 왔어."], list(CONTRACT_PREMISES), backend)
    assert r.c_score == -1.0
    assert r.contradict_rate == 1.0  # I2 독립 날조 알람
    assert r.per_sentence[0][1] is NLILabel.CONTRADICT


def test_c_score_neutral_unweighted():
    # 토큰 공유 0, 모순 마커 0 → 전부 NEUTRAL. c_score 0, 알람 0.
    backend = MockNLIBackend()
    r = c_score(["xyzzy"], ["zzzz"], backend)
    assert r.c_score == 0.0
    assert r.contradict_rate == 0.0
    assert r.n_neutral == 1


def test_c_score_conservative_aggregation():
    # 한 문장이 ENTAIL premise 와도 매칭되지만 모순 마커도 보유
    # → 보수적 집계상 CONTRADICT 가 지배.
    backend = MockNLIBackend(contradict_markers=("수영",))
    r = c_score(["조용한 결인데 수영 갔어"], ["조용한 결"], backend)
    assert r.per_sentence[0][1] is NLILabel.CONTRADICT
    assert r.n_contradict == 1 and r.n_entail == 0


def test_c_score_fail_open_on_backend_exception():
    class Boom:
        def classify(self, premise, hypothesis):
            raise RuntimeError("backend down")

    r = c_score(["무슨 말이든."], ["아무 premise"], Boom())
    # 예외가 새지 않고 NEUTRAL 로 흘러 유효한 결과.
    assert r.n_neutral == 1
    assert r.c_score == 0.0


def test_module_has_no_toplevel_heavy_import():
    # torch/transformers 가 모듈 top-level 에서 import 되면 안 된다
    # (992 baseline 이 torch 없이 돌아가야 함). 결정론적 소스 스캔.
    src = (
        Path(__file__).parent / "persona_eval" / "nli.py"
    ).read_text(encoding="utf-8")
    for line in src.splitlines():
        if line and not line[0].isspace():  # top-level 만
            assert not line.startswith("import torch")
            assert not line.startswith("import transformers")
            assert not line.startswith("from transformers")
            assert not line.startswith("from torch")
