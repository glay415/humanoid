"""5개 드라이브 충족도 + 결핍도 계산.

호기심 = 1 - novelty_ema
유대   = bonding (내부 상태 직접 매핑)
보존   = self_model.confidence (인터페이스 경유, 반자동)
안전   = 1 - stress
쾌락   = reward
"""

from low_level.spec_invariants import (
    SpecViolation,
    _LL_TOKEN,
    assert_low_level,
)


# spec §8.3: 드라이브를 끌 수 없다. ``disable()`` / ``enable()`` 은
# 토큰 게이팅. 정상 코드에서는 호출되지 않는다 (현재 API 자체가 없음).
# 누군가 high-level 에서 disable() 을 호출하려 시도하면 SpecViolation.

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
        # spec §8.3 — 활성/비활성 플래그. 항상 True. disable() 은 토큰을 요구하나,
        # 토큰을 가진 어떤 정상 경로도 disable 호출하지 않는다 (드라이브를 끌
        # 일이 없음). 명시적으로 SpecViolation 을 raise 한다.
        self._enabled: bool = True

    def disable(self, token: object = None) -> None:
        """spec §8.3: 드라이브 비활성화 — 항상 SpecViolation.

        토큰 검사 전에 명시적으로 raise. 토큰이 있어도 (low_level 내부에서
        호출되어도) spec §8.3 위반이므로 차단. 이 함수의 존재 자체가 invariant
        를 강제하기 위한 trap 이다.
        """
        raise SpecViolation(
            "spec §8.3 — drives cannot be disabled. "
            "If a drive's deficit feels overwhelming, lower its ratio in the "
            "temperament yaml or reduce the input that raises it; do not turn "
            "the drive off."
        )

    def enable(self, token: object = None) -> None:
        """대칭적으로 enable() 도 차단 — 항상 활성 상태가 spec.

        disable 자체가 막혀 있으므로 enable 도 의미가 없다.
        """
        raise SpecViolation(
            "spec §8.3 — drives are always enabled by spec; nothing to enable."
        )

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
