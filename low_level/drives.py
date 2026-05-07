"""5개 드라이브 충족도 + 결핍도 계산.

호기심 = 1 - novelty_ema
유대   = bonding (내부 상태 직접 매핑)
보존   = self_model.confidence (인터페이스 경유, 반자동)
안전   = 1 - stress
쾌락   = reward
"""


class Drives:
    """드라이브 충족도/결핍도 관리."""

    NAMES = ['curiosity', 'bonding', 'preservation', 'safety', 'pleasure']

    def __init__(
        self,
        drive_ratios: dict[str, float],
        novelty_ema_alpha: float = 0.1,
    ):
        self.ratios = drive_ratios
        self.novelty_ema = 0.0
        self.novelty_ema_alpha = novelty_ema_alpha
        # 보존 드라이브는 고수준 의존 — 마지막 알려진 confidence 캐시
        self._preservation_value: float = 0.1  # 초기: 자기 모델 confidence 초기값

    def update_novelty_ema(self, novelty: float) -> None:
        """novelty EMA 업데이트. 경험 벡터의 novelty 차원을 매 턴 전달."""
        self.novelty_ema += self.novelty_ema_alpha * (novelty - self.novelty_ema)

    def set_preservation(self, confidence: float) -> None:
        """인터페이스 경유: 자기 모델 confidence가 변할 때만 호출."""
        self._preservation_value = confidence

    def compute(self, state: dict[str, float]) -> dict:
        """충족도 + 결핍도 계산. 반환: {fulfillment, deficits, max_deficit}."""
        fulfillment = {
            'curiosity': 1.0 - self.novelty_ema,
            'bonding': state['bonding'],
            'preservation': self._preservation_value,
            'safety': 1.0 - state['stress'],
            'pleasure': state['reward'],
        }

        deficits = {}
        for name in self.NAMES:
            deficits[name] = self.ratios[name] * (1.0 - fulfillment[name])

        max_deficit = max(deficits.values()) if deficits else 0.0

        return {
            'fulfillment': fulfillment,
            'deficits': deficits,
            'max_deficit': max_deficit,
        }
