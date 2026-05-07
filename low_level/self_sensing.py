"""자기감지 — 내부 상태 + 드라이브 + 코어 어펙트 → 신호 상승 원료.

정밀도 손실은 interface/signal_rise.py에서 적용.
여기서는 원시 수치를 모아서 전달만 함.
"""


class SelfSensing:
    """자기감지 모듈. 저수준 수치를 모아서 인터페이스에 전달할 원료 생성."""

    def generate(
        self,
        state: dict[str, float],
        drives: dict,
        raw_core_affect: dict[str, float],
    ) -> dict:
        """내부 상태 전체를 원시 자기감지 신호로 패키징."""
        return {
            'state': state,
            'drives': drives,
            'raw_core_affect': raw_core_affect,
        }
