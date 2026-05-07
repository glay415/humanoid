"""신호 상승 — 저수준 숫자 → 고수준 자연어 변환.

정밀도 손실 = 자기 인식의 해상도 (인위적 노이즈 아님).
final_core_affect 보정 (meta_resource) 도 여기서 수행.
"""

import numpy as np


class SignalRise:
    """저수준 숫자 → 고수준 자연어 변환 + meta_resource 보정."""

    RESOLUTION_LEVELS = {
        2: ['없음', '있음'],
        3: ['낮음', '중간', '높음'],
        5: ['매우 낮음', '낮음', '중간', '높음', '매우 높음'],
    }

    def __init__(self, resolution: int = 3, meta_beta: float = 0.08):
        self.resolution = resolution
        self.labels = self.RESOLUTION_LEVELS[resolution]
        self.meta_beta = meta_beta

    def quantize(self, value: float, param_name: str) -> str:
        """0.0~1.0 → 자연어 라벨 (해상도에 따른 정밀도 손실)."""
        idx = min(int(value * self.resolution), self.resolution - 1)
        return f"{param_name}이(가) {self.labels[idx]}"

    def generate_self_signal(
        self,
        state: dict[str, float],
        drives: dict,
        raw_core_affect: dict[str, float],
    ) -> str:
        """내부 상태 전체를 자연어 자기감지 신호로 변환."""
        signals = []
        for param, value in state.items():
            signals.append(self.quantize(value, param))
        valence_word = "긍정적" if raw_core_affect['valence'] > 0 else "부정적"
        signals.append(f"전반적 기분이 {valence_word}")
        return ". ".join(signals)

    def apply_meta_correction(
        self,
        raw_core_affect: dict[str, float],
        meta_resource: float,
    ) -> dict[str, float]:
        """raw_core_affect + 메타자원 보정 → final_core_affect."""
        final = dict(raw_core_affect)
        final['valence'] = float(np.clip(
            raw_core_affect['valence'] - self.meta_beta * (1.0 - meta_resource),
            -1.0, 1.0,
        ))
        return final

    def generate_marker_signal(self, markers: list) -> str:
        """경험 마커 목록을 자연어로 변환 (정밀도 손실 포함). 빈 리스트면 '관련 마커 없음'.

        markers: low_level.markers.Marker dataclass 인스턴스 리스트, 또는 valence/strength
        키를 가진 dict 리스트. 둘 다 허용.
        """
        if not markers:
            return "(관련 경험 마커 없음)"
        parts = []
        for m in markers:
            # dataclass 와 dict 모두 지원
            v = getattr(m, 'valence', None)
            if v is None:
                v = m.get('valence', 0.0) if isinstance(m, dict) else 0.0
            s = getattr(m, 'strength', None)
            if s is None:
                s = m.get('strength', 0.0) if isinstance(m, dict) else 0.0
            approach = "접근" if v > 0 else ("회피" if v < 0 else "중립")
            # 강도를 라벨로 양자화 (정밀도 손실)
            intensity = self.labels[min(int(s * self.resolution), self.resolution - 1)]
            parts.append(f"{approach}({intensity})")
        return ", ".join(parts)
