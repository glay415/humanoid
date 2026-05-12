"""자기 모델 CRUD.

초기 시드 — 페르소나 기반. DMN이 경험을 통해 점진적으로 갱신.
"""

from __future__ import annotations


DEFAULT_NARRATIVE = (
    '호기심이 많고 따뜻한 성격이다. '
    '새로운 사람과 대화하는 게 즐겁다. '
    '가까운 친구처럼 편하게 말하고 듣는다.'
)


# ADR-017 — DMN Activity 3 의 narrative_delta 를 self_model.narrative 에 적용할
# 때 쓰는 section 헤더. 본 헤더 이후의 줄들은 DMN 이 누적 관리하는 자기 서사
# 갱신 라인 — 최신이 위에, 오래된 게 아래. ``MAX_DELTAS`` 초과 시 가장 오래된
# 항목 drop.
_INTERNALIZED_HEADER = '[누적 자기인식 (DMN)]'
_MAX_DELTAS = 5


class SelfModel:
    """자기 모델 관리."""

    def __init__(self):
        self.data: dict = {
            'narrative': DEFAULT_NARRATIVE,
            'goals': [],
            'emotions': {},
            'confidence': 0.5,
            'relationship_stage': None,
        }

    @property
    def confidence(self) -> float:
        return self.data['confidence']

    def update(self, updates: dict) -> None:
        self.data.update(updates)

    def to_dict(self) -> dict:
        return dict(self.data)

    # -------------------------------------------------------------- ADR-017
    def add_internalized_delta(self, delta: str, *, max_deltas: int = _MAX_DELTAS) -> None:
        """DMN Activity 3 가 만든 narrative_delta 한 줄을 self_narrative 에 누적.

        narrative 끝에 ``[누적 자기인식 (DMN)]`` 헤더 section 을 만들고 그 안에
        delta 를 ``- <line>`` 형태로 추가한다. 가장 최근이 위, 오래된 게 아래.
        ``max_deltas`` 초과 시 가장 오래된 줄을 drop.

        delta 가 빈 문자열이면 no-op (DMN LLM 이 빈 응답을 흘리는 가드).
        """
        delta = (delta or '').strip()
        if not delta:
            return
        # 한 줄로만 받는다 — 다중 라인이 와도 첫 비공백 라인만 사용.
        first_line = next(
            (line.strip() for line in delta.splitlines() if line.strip()),
            '',
        )
        if not first_line:
            return

        existing = (self.data.get('narrative') or '').rstrip()
        before, sep, after = existing.partition(_INTERNALIZED_HEADER)
        if not sep:
            # 헤더 없음 → 새로 만들어 추가.
            base = existing
            existing_deltas: list[str] = []
        else:
            base = before.rstrip()
            # 헤더 다음 줄들에서 '- ' 로 시작하는 라인만 추출.
            existing_deltas = []
            for line in after.splitlines():
                stripped = line.strip()
                if stripped.startswith('- '):
                    existing_deltas.append(stripped[2:].strip())

        # 새 delta 최상단, 중복은 dedupe (정확히 동일 텍스트만).
        deltas: list[str] = [first_line]
        for d in existing_deltas:
            if d and d != first_line and d not in deltas:
                deltas.append(d)
            if len(deltas) >= max_deltas:
                break

        rebuilt_section = (
            _INTERNALIZED_HEADER + '\n' + '\n'.join(f'- {d}' for d in deltas)
        )
        if base:
            self.data['narrative'] = base + '\n\n' + rebuilt_section
        else:
            self.data['narrative'] = rebuilt_section
