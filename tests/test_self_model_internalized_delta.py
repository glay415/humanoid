"""ADR-017 — SelfModel.add_internalized_delta 단위 테스트.

DMN Activity 3 가 만든 narrative_delta 가 self_model.narrative 에 누적 section
으로 적용되는지 검증.
"""
from __future__ import annotations

from storage.self_model import SelfModel, _INTERNALIZED_HEADER


# ---------------------------------------------------------------------------
# 1) 첫 delta — 헤더 + 1 라인 추가
# ---------------------------------------------------------------------------


def test_first_delta_creates_header_and_line():
    sm = SelfModel()
    base = sm.data['narrative']
    sm.add_internalized_delta('타인의 거리감에 예민한 편이라는 걸 알게 됐다.')

    out = sm.data['narrative']
    assert base in out
    assert _INTERNALIZED_HEADER in out
    assert '- 타인의 거리감에 예민한 편이라는 걸 알게 됐다.' in out


# ---------------------------------------------------------------------------
# 2) 여러 delta — 최신이 위로 누적
# ---------------------------------------------------------------------------


def test_multiple_deltas_stack_with_newest_on_top():
    sm = SelfModel()
    sm.add_internalized_delta('첫째')
    sm.add_internalized_delta('둘째')
    sm.add_internalized_delta('셋째')

    out = sm.data['narrative']
    header_idx = out.index(_INTERNALIZED_HEADER)
    after_header = out[header_idx:]
    # '- 셋째' 가 '- 둘째' 보다 먼저, '- 둘째' 가 '- 첫째' 보다 먼저.
    assert after_header.index('- 셋째') < after_header.index('- 둘째')
    assert after_header.index('- 둘째') < after_header.index('- 첫째')


# ---------------------------------------------------------------------------
# 3) 5 개 cap — 가장 오래된 게 drop
# ---------------------------------------------------------------------------


def test_max_deltas_cap_drops_oldest():
    sm = SelfModel()
    for i in range(1, 8):
        sm.add_internalized_delta(f'line-{i}')

    out = sm.data['narrative']
    # 최신 5 개만 남아야 한다 — line-7, line-6, line-5, line-4, line-3.
    assert '- line-7' in out
    assert '- line-3' in out
    assert '- line-2' not in out
    assert '- line-1' not in out


# ---------------------------------------------------------------------------
# 4) 빈 delta — no-op
# ---------------------------------------------------------------------------


def test_empty_or_whitespace_delta_is_noop():
    sm = SelfModel()
    base = sm.data['narrative']
    sm.add_internalized_delta('')
    sm.add_internalized_delta('   \n  ')
    assert sm.data['narrative'] == base
    assert _INTERNALIZED_HEADER not in sm.data['narrative']


# ---------------------------------------------------------------------------
# 5) 중복 delta — dedupe
# ---------------------------------------------------------------------------


def test_duplicate_delta_is_deduped():
    sm = SelfModel()
    sm.add_internalized_delta('같은 문장')
    sm.add_internalized_delta('다른 문장')
    sm.add_internalized_delta('같은 문장')  # 다시 추가

    out = sm.data['narrative']
    # '같은 문장' 등장 횟수 = 1 (최상단으로 올라옴).
    assert out.count('- 같은 문장') == 1


# ---------------------------------------------------------------------------
# 6) 다중 라인 delta — 첫 비공백 라인만 사용
# ---------------------------------------------------------------------------


def test_multiline_delta_takes_first_nonblank_line():
    sm = SelfModel()
    sm.add_internalized_delta('한 줄.\n두 줄.\n세 줄.')
    out = sm.data['narrative']
    assert '- 한 줄.' in out
    assert '- 두 줄.' not in out


# ---------------------------------------------------------------------------
# 7) 기존 narrative 보존
# ---------------------------------------------------------------------------


def test_base_narrative_preserved_above_section():
    sm = SelfModel()
    sm.update({'narrative': '나는 음악을 좋아한다.'})
    sm.add_internalized_delta('재즈가 특히 좋다는 걸 인정.')

    out = sm.data['narrative']
    base_idx = out.index('나는 음악을 좋아한다.')
    header_idx = out.index(_INTERNALIZED_HEADER)
    assert base_idx < header_idx, 'base narrative 가 header 위에 있어야 함'


# ---------------------------------------------------------------------------
# 8) 헤더가 이미 있는 narrative — section 만 수정
# ---------------------------------------------------------------------------


def test_existing_header_section_updated_in_place():
    sm = SelfModel()
    sm.add_internalized_delta('첫번째')
    # 두 번째 호출은 기존 section 안에 추가.
    sm.add_internalized_delta('두번째')

    out = sm.data['narrative']
    # 헤더는 *한 번만* 등장.
    assert out.count(_INTERNALIZED_HEADER) == 1
