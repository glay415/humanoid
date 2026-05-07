"""DMN (Default Mode Network) — 유휴 시 작동.

우선순위 큐: 미평가 재처리 > 반추 > 사례 승격 > 지식 내면화 > 사색.
대화 중: LLM 호출 안 함. 기억 인출 associativeness에만 영향.
Phase 5에서 구현.
"""


class DMN:
    """DMN 모듈."""

    def __init__(self, base_activity: float = 0.5):
        self.activity: float = base_activity  # 0~1 연속값

    async def run_cycle(self) -> dict | None:
        """DMN 사이클 1회 실행. Phase 5에서 구현."""
        raise NotImplementedError("Phase 5")
