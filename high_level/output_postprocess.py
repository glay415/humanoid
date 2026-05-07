"""⑤ 출력 후처리 — 톤 검증 + 응답 지연.

톤 검증 복합 조건:
  재생성: sign(response) ≠ sign(state) AND |Δ| > 0.5
  톤 조정: |Δ| > 0.3 AND 같은 극성
  통과: |Δ| ≤ 0.3
Phase 4에서 구현.
"""


class OutputPostprocess:
    """출력 후처리 모듈."""

    async def process(
        self,
        response: dict,
        final_core_affect: dict[str, float],
    ) -> str:
        """톤 검증 + 응답 지연. 반환: 최종 응답 텍스트."""
        raise NotImplementedError("Phase 4")
