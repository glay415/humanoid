"""ADR-020 — SelfModel.add_contemplation + Activity 3 / Activity 4 의 두 section
분리 보존 검증.
"""
from __future__ import annotations

from storage.self_model import SelfModel, _CONTEMPLATION_HEADER, _INTERNALIZED_HEADER


# ---------------------------------------------------------------------------
# 1) 첫 contemplation — [혼잣말] 헤더 + 1 라인
# ---------------------------------------------------------------------------


def test_first_contemplation_creates_header_and_line():
    sm = SelfModel()
    sm.add_contemplation('오늘은 조용히 있고 싶다.')
    out = sm.data['narrative']
    assert _CONTEMPLATION_HEADER in out
    assert '- 오늘은 조용히 있고 싶다.' in out


# ---------------------------------------------------------------------------
# 2) 두 section 분리 보존 — [누적 자기인식] + [혼잣말] 동시 존재
# ---------------------------------------------------------------------------


def test_internalized_and_contemplation_sections_coexist():
    sm = SelfModel()
    sm.add_internalized_delta('재즈를 좋아하는 결이 있다.')
    sm.add_contemplation('누군가 보고 싶다.')

    out = sm.data['narrative']
    # 두 헤더 모두 등장.
    assert _INTERNALIZED_HEADER in out
    assert _CONTEMPLATION_HEADER in out
    # 두 라인 모두 보존.
    assert '- 재즈를 좋아하는 결이 있다.' in out
    assert '- 누군가 보고 싶다.' in out
    # 헤더 한 번씩만.
    assert out.count(_INTERNALIZED_HEADER) == 1
    assert out.count(_CONTEMPLATION_HEADER) == 1


# ---------------------------------------------------------------------------
# 3) 한 section 갱신 시 다른 section 보존
# ---------------------------------------------------------------------------


def test_updating_one_section_preserves_the_other():
    sm = SelfModel()
    sm.add_internalized_delta('첫 통찰')
    sm.add_contemplation('첫 사색')

    # 같은 section 에 추가.
    sm.add_internalized_delta('둘째 통찰')
    sm.add_contemplation('둘째 사색')

    out = sm.data['narrative']
    # 두 통찰 / 두 사색 모두 보존.
    assert '- 첫 통찰' in out
    assert '- 둘째 통찰' in out
    assert '- 첫 사색' in out
    assert '- 둘째 사색' in out

    # 두 section 의 헤더는 각각 한 번씩.
    assert out.count(_INTERNALIZED_HEADER) == 1
    assert out.count(_CONTEMPLATION_HEADER) == 1


# ---------------------------------------------------------------------------
# 4) Contemplation 도 cap 적용
# ---------------------------------------------------------------------------


def test_contemplation_cap_drops_oldest():
    sm = SelfModel()
    for i in range(1, 8):
        sm.add_contemplation(f'사색-{i}')

    out = sm.data['narrative']
    # 최신 5 개만.
    assert '- 사색-7' in out
    assert '- 사색-3' in out
    assert '- 사색-2' not in out


# ---------------------------------------------------------------------------
# 5) 두 section 이 cap 독립적으로 동작
# ---------------------------------------------------------------------------


def test_two_sections_capped_independently():
    sm = SelfModel()
    # 통찰 5 개.
    for i in range(1, 6):
        sm.add_internalized_delta(f'통찰-{i}')
    # 사색 5 개.
    for i in range(1, 6):
        sm.add_contemplation(f'사색-{i}')

    out = sm.data['narrative']
    # 각각 5 줄 — 합쳐서 10 줄.
    bullet_count = out.count('\n- ')
    # bullets 없는 마지막 라인 (첫 bullet) 도 한 번 (- 가 줄 시작이므로).
    # 더 단순하게: 두 section 각각 5 개씩 있는지.
    for i in range(1, 6):
        assert f'- 통찰-{i}' in out
        assert f'- 사색-{i}' in out


# ---------------------------------------------------------------------------
# 6) 빈 reflection — no-op
# ---------------------------------------------------------------------------


def test_empty_contemplation_is_noop():
    sm = SelfModel()
    base = sm.data['narrative']
    sm.add_contemplation('')
    sm.add_contemplation('   ')
    assert sm.data['narrative'] == base
    assert _CONTEMPLATION_HEADER not in sm.data['narrative']
