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
# ADR-020 — DMN Activity 4 (contemplate) 의 사색 한 줄을 별도 section 으로.
# Activity 3 (외부 자극 → 자기이해) 과 결이 달라 (드라이브 결핍 자유 연상),
# 같은 section 에 섞으면 톤이 흐려질 위험. 의도적으로 분리.
_CONTEMPLATION_HEADER = '[혼잣말 (DMN 사색)]'
_MAX_DELTAS = 5


class SelfModel:
    """자기 모델 관리."""

    def __init__(self, narrative_pressure: float = 0.5):
        # ADR-030: narrative_pressure (0~1) 가 [누적 자기인식] / [혼잣말] section
        # 의 cap 을 결정. default 0.5 → max_lines=5 (기존 동작 보존). 1.0 → 10,
        # 0.0 → 1 (최소). 높은 pressure 페르소나는 self_narrative 가 더 풍부하게
        # 누적되어 unified_response prompt 에 더 큰 영향.
        self._narrative_pressure = max(0.0, min(1.0, float(narrative_pressure)))
        self.data: dict = {
            'narrative': DEFAULT_NARRATIVE,
            'goals': [],
            'emotions': {},
            'confidence': 0.5,
            'relationship_stage': None,
        }

    def _effective_max_lines(self, default: int = _MAX_DELTAS) -> int:
        """ADR-030 — narrative_pressure 를 section cap 으로 변환.
        pressure=0.5 (default) → cap 5. pressure=1.0 → cap 10. pressure=0.0 → cap 1.
        """
        return max(1, int(round(default * 2.0 * self._narrative_pressure)))

    @property
    def confidence(self) -> float:
        return self.data['confidence']

    def update(self, updates: dict) -> None:
        self.data.update(updates)

    def to_dict(self) -> dict:
        return dict(self.data)

    # -------------------------------------------------------------- ADR-017 / 020
    def _add_to_section(
        self,
        section_header: str,
        line: str,
        *,
        max_lines: int = _MAX_DELTAS,
    ) -> None:
        """generic helper — narrative 안의 특정 헤더 section 에 한 줄 누적.

        ADR-017 (`[누적 자기인식 (DMN)]`) 과 ADR-020 (`[혼잣말 (DMN 사색)]`) 둘 다
        같은 누적 정책을 쓰지만 *섹션은 독립* — 두 section 은 결이 달라 섞이면
        톤이 흐려진다. 본 helper 는 한 section 의 누적만 책임지고, 다른 section
        은 건드리지 않는다.

        - 새 line 은 section 의 *최상단* 에 (최신이 위).
        - dedupe — 동일 텍스트가 이미 있으면 한 번만 (최상단으로 올라옴).
        - ``max_lines`` 초과 시 가장 오래된 라인 drop.
        - 빈/공백 line 은 no-op. 다중 라인은 첫 비공백 라인만.
        - 같은 narrative 안에 다른 section 들 (헤더가 다른) 은 보존.
        """
        line = (line or '').strip()
        if not line:
            return
        first = next(
            (raw.strip() for raw in line.splitlines() if raw.strip()),
            '',
        )
        if not first:
            return

        existing = (self.data.get('narrative') or '').rstrip()
        before, sep, after = existing.partition(section_header)
        if not sep:
            base_with_other_sections = existing
            existing_lines: list[str] = []
            tail_after_section = ''
        else:
            # `after` 는 현 section 의 본문 + 그 뒤 다른 section 들 (있다면).
            # 첫 빈 줄 또는 다음 section header 까진 본 section 의 라인이고,
            # 그 뒤는 보존해야 할 tail.
            base_with_other_sections = before.rstrip()
            after_lines = after.splitlines()
            current_section_lines: list[str] = []
            tail_lines: list[str] = []
            in_tail = False
            for raw in after_lines:
                stripped = raw.strip()
                if in_tail:
                    tail_lines.append(raw)
                    continue
                if stripped.startswith('- '):
                    current_section_lines.append(stripped[2:].strip())
                elif stripped == '' and not current_section_lines:
                    # 헤더 바로 다음 빈 줄 — 단순 separator, 무시.
                    continue
                elif stripped == '':
                    # 첫 bullet 이후의 빈 줄 — 본 section 종료, 뒷줄은 tail.
                    in_tail = True
                else:
                    # 다른 section header 등 — tail.
                    in_tail = True
                    tail_lines.append(raw)
            existing_lines = current_section_lines
            tail_after_section = '\n'.join(tail_lines).rstrip()

        # 새 line 최상단, dedupe, cap.
        lines_out: list[str] = [first]
        for existing_line in existing_lines:
            # cap 체크는 append *전* — 그래야 cap=1 일 때도 정확히 1 라인 유지.
            if len(lines_out) >= max_lines:
                break
            if existing_line and existing_line != first and existing_line not in lines_out:
                lines_out.append(existing_line)

        rebuilt_section = (
            section_header + '\n' + '\n'.join(f'- {x}' for x in lines_out)
        )
        parts: list[str] = []
        if base_with_other_sections:
            parts.append(base_with_other_sections)
        parts.append(rebuilt_section)
        if tail_after_section:
            parts.append(tail_after_section)
        self.data['narrative'] = '\n\n'.join(parts)

    def add_internalized_delta(self, delta: str, *, max_deltas: int | None = None) -> None:
        """DMN Activity 3 (knowledge_internalize) 가 만든 narrative_delta 누적.

        ``[누적 자기인식 (DMN)]`` section 에 한 줄씩 쌓는다. 자세한 정책은
        ``_add_to_section`` doc 참조.

        ADR-030: max_deltas 가 None 이면 ``_narrative_pressure`` 기반 cap 사용.
        """
        cap = max_deltas if max_deltas is not None else self._effective_max_lines()
        self._add_to_section(_INTERNALIZED_HEADER, delta, max_lines=cap)

    def add_contemplation(self, reflection: str, *, max_lines: int | None = None) -> None:
        """ADR-020 — DMN Activity 4 (contemplate) 가 만든 사색 한 줄을 누적.

        ``[혼잣말 (DMN 사색)]`` 별도 section 에 한 줄씩. Activity 3 의 외부 자극
        기반 자기이해와 결이 다르므로 (드라이브 결핍 자유 연상), 의도적으로
        섹션 분리. 같은 누적 정책 (최신 위, dedupe, max_lines cap, oldest drop).

        ADR-030: max_lines 가 None 이면 ``_narrative_pressure`` 기반 cap 사용.
        """
        cap = max_lines if max_lines is not None else self._effective_max_lines()
        self._add_to_section(_CONTEMPLATION_HEADER, reflection, max_lines=cap)
