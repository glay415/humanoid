# 구현 명세 — 인지 아키텍처 v12

> cognitive-architecture-v12-spec.md의 구현을 위한 기술 스펙

1. 프로젝트 뼈대 — pyproject.toml + 디렉토리 구조 생성 + numpy, pydantic, pyyaml, pytest 설치

2. config/temperament_default.yaml — 그대로 옮기면 됨

3. internal_state.py — 9파라미터 + A/W/D 행렬 + update() + apply_fast_path() + validate_stability()

4. drives.py — 5개 드라이브 충족도 + 결핍도 계산

5. emotion_base.py — update_raw_core_affect() + update_mood()

6. markers.py — 마커 형성/감쇠/갱신

7. temperament.py — YAML 로드 + EMA 표류

8. pipeline.py — 1→2→3→4→5 고정 순서 조립

9. 테스트 — test_stability.py (고유값), test_drives.py, test_markers.py, 수동 경험 벡터 주입 200턴 시뮬레이션

---

## 1. 기술 선택 근거

### 언어: Python

- LLM API 생태계 (OpenAI SDK, Anthropic SDK, LiteLLM) — Python이 1등 지원
- 벡터 DB 클라이언트 (ChromaDB, Qdrant) — Python 네이티브
- 수치 연산 (NumPy) — 행렬곱 마이크로초 단위
- 병목은 LLM API 호출 레이턴시(수 초). Python 인터프리터 속도가 문제 될 지점 없음
- 연구 프로젝트 성격: "빠르게 돌려보고 파라미터 튜닝"이 핵심

### 기술 스택

| 층 | 기술 | 이유 |
|---|---|---|
| LLM 호출 | LiteLLM 또는 직접 SDK | 큰/작은 모델 혼합. OpenAI/Anthropic/로컬 모델 전환 용이 |
| 작은 모델 | Claude Haiku / GPT-4o-mini / 로컬(Ollama) | 감정 평가, 사회인지. 빠르고 저렴해야 함 |
| 큰 모델 | Claude Sonnet~Opus / GPT-4o | 후보 생성, 최종 판단. 품질이 중요 |
| 벡터 DB | ChromaDB (로컬) 또는 Qdrant | 기억 검색. 감정 태그 메타데이터 필터링 지원 필수 |
| 일반 DB | SQLite → PostgreSQL | 자기/타자 모델, 기질, 내부 상태. 시작은 SQLite |
| 수치 연산 | NumPy | 상호작용 행렬, leaky integral, 감쇠 |
| 비동기 | asyncio + aiohttp | 사회인지 ‖ 기억 인출 병렬 호출 |
| 이벤트 버스 | 자체 구현 (경량) | Kafka 등 외부 MQ는 과잉. 인메모리 pub/sub |
| 설정/기질 | YAML | 기질 파라미터 세트를 파일로 관리. 다른 "사람" = 다른 설정 |
| 테스트 | pytest + 시나리오 스위트 | 27 시나리오별 기대 상태 패턴 → 자동화 |
| 인터페이스 (초기) | CLI | 터미널 대화. 나중에 웹소켓/웹 UI |

---

## 2. 프로젝트 구조

```
humanoid/
├── config/
│   ├── temperament_default.yaml     # 기질 파라미터 세트 (기본)
│   ├── temperament_test.yaml        # 테스트 모드 (N=5, M=20, K=100)
│   └── models.yaml                  # LLM 모델 설정 (큰/작은/DMN)
│
├── core/
│   ├── __init__.py
│   ├── orchestrator.py              # 시스템 레벨: 턴 관리, 트리거 발동
│   ├── trigger_registry.py          # 트리거 등록/발동/우선순위 해소
│   ├── event_bus.py                 # 고수준 이벤트 버스 (인메모리 pub/sub)
│   └── turn.py                      # 턴 유형 정의 (대화/DMN/정비), 우선순위
│
├── low_level/
│   ├── __init__.py
│   ├── pipeline.py                  # 고정 파이프라인 (1→2→3→4)
│   ├── internal_state.py            # 9 파라미터 + 상호작용 행렬 (NumPy)
│   ├── emotion_base.py              # raw 코어 어펙트, 기분(leaky integral)
│   ├── drives.py                    # 5 드라이브 충족도 계산
│   ├── markers.py                   # 경험 마커 수치 관리 (valence, strength, 감쇠)
│   ├── self_sensing.py              # 자기감지 + 정밀도 손실 (→ interface로 전달)
│   ├── fast_path.py                 # 빠른 경로 패턴 매칭
│   └── temperament.py               # 기질 로드, EMA 표류 계산
│
├── high_level/
│   ├── __init__.py
│   ├── emotion_appraisal.py         # ① 감정 평가 (작은 모델)
│   ├── social_cognition.py          # ② 사회인지 (작은 모델)
│   ├── memory_retrieval.py          # ② 기억 인출 (벡터 검색 + 감정태그 + 전망큐)
│   ├── candidate_generation.py      # ③ 후보 생성 (큰 모델)
│   ├── final_judgment.py            # ④ 최종 판단 (큰 모델)
│   ├── output_postprocess.py        # ⑤ 톤 검증 + 응답 지연
│   ├── metacognition.py             # 메타인지 (모니터링, 통제, 자원 관리)
│   └── dmn.py                       # DMN (우선순위 큐, 반추, 승격, 사색)
│
├── storage/
│   ├── __init__.py
│   ├── memory_store.py              # 일화/의미/절차/전망 기억 CRUD
│   ├── marker_store.py              # 경험 마커 CRUD (절차기억 하위 유형)
│   ├── vector_db.py                 # 벡터 DB 래퍼 (ChromaDB)
│   ├── self_model.py                # 자기 모델 CRUD
│   ├── other_model.py               # 타자 모델 CRUD (베이지안 가중 평균)
│   └── snapshot.py                  # 턴 기반 잠금, 스냅샷/트랜잭션 관리
│
├── interface/
│   ├── __init__.py
│   ├── signal_rise.py               # ↑ 저→고 신호 변환 (정밀도 손실 적용) + final_core_affect 보정
│   ├── experience_descent.py        # ↓ 고→저 경험 벡터 전달
│   └── schemas.py                   # 이벤트 스키마 정의 (Pydantic)
│
├── prompts/                         # LLM 프롬프트 템플릿 (코드와 분리)
│   ├── emotion_appraisal.txt        # ① 감정 평가 프롬프트
│   ├── social_cognition.txt         # ② 사회인지 프롬프트
│   ├── candidate_generation.txt     # ③ 후보 생성 프롬프트
│   ├── final_judgment.txt           # ④ 최종 판단 프롬프트
│   └── tone_verification.txt        # ⑤ 톤 검증 프롬프트
│
├── tests/
│   ├── scenarios/                   # 27개 시나리오 테스트
│   │   ├── test_yearning.py
│   │   ├── test_regret.py
│   │   ├── test_burnout.py
│   │   ├── test_love.py
│   │   ├── test_trauma_flashback.py
│   │   └── ...
│   ├── test_stability.py            # 행렬 안정성 (고유값 검증)
│   ├── test_reconsolidation.py      # 재고정화 블렌딩 검증
│   ├── test_low_level.py            # 저수준 파이프라인 단위 테스트
│   └── test_lifecycle.py            # 전체 라이프사이클 (테스트 모드 200턴)
│
├── main.py                          # 진입점 (CLI 대화 루프)
├── pyproject.toml                   # 의존성 관리
└── README.md
```

---

## 3. 모듈 설계

### 3.1 저수준 파이프라인 (`low_level/`)

**목표:** LLM 없이 독립 작동 가능한 순수 수치 시스템.

#### `internal_state.py` — 핵심 수치 엔진

```python
import numpy as np

class InternalState:
    PARAMS = ['reward', 'patience', 'arousal', 'learning',
              'excitation', 'inhibition', 'stress', 'bonding', 'comfort']

    # 경험 벡터 차원 순서 — A 행렬 열 순서와 반드시 일치
    EXP_DIMS = ['reward', 'novelty', 'threat', 'social_reward', 'goal_progress']

    def __init__(self, baselines: dict[str, float]):
        self.state = np.array([baselines[p] for p in self.PARAMS])  # (9,)
        self.baselines = self.state.copy()
        # A: 경험 벡터(5) → 내부 상태(9) 매핑. Phase 6에서 시나리오 기반 튜닝.
        # 열 순서: [reward, novelty, threat, social_reward, goal_progress]
        # 행 순서: PARAMS (reward, patience, arousal, learning, excite, inhibit, stress, bonding, comfort)
        self.A = np.array([
            # rew   nov   thr   soc   goal
            [+0.3, +0.1,  0.0,  0.0, +0.1],  # reward
            [ 0.0,  0.0,  0.0,  0.0,  0.0],  # patience
            [ 0.0, +0.2, +0.2,  0.0,  0.0],  # arousal
            [ 0.0, +0.2,  0.0,  0.0,  0.0],  # learning
            [+0.2, +0.1,  0.0,  0.0,  0.0],  # excitation
            [ 0.0,  0.0, +0.2,  0.0,  0.0],  # inhibition
            [ 0.0,  0.0, +0.3,  0.0, -0.1],  # stress
            [ 0.0,  0.0,  0.0, +0.3,  0.0],  # bonding
            [+0.1,  0.0, -0.1, +0.1,  0.0],  # comfort
        ])
        # W: 내부 상태 간 상호작용 행렬(9×9). 핵심 기제. 대각 = 0.
        # 부호는 명세 확정, 크기는 Phase 6 튜닝 대상. 아래는 초기 시드.
        # 안정성 검증 통과 확인: J=W-D 고유값 전부 음수 (max = -0.01)
        self.W = np.array([
            #  rew    pat    aro    lrn    exc    inh    str    bnd    cmf
            [ 0.0,  -0.06,  0.0,   0.0,  +0.02,  0.0,  -0.02,  0.0,  +0.02],  # reward↑ →
            [-0.06,  0.0,   0.0,   0.0,   0.0,  +0.02,  0.0,   0.0,   0.0 ],  # patience↑ →
            [ 0.0,   0.0,   0.0,  -0.06, +0.02,  0.0,  +0.02,  0.0,   0.0 ],  # arousal↑ →
            [ 0.0,   0.0,  -0.06,  0.0,   0.0,   0.0,   0.0,   0.0,   0.0 ],  # learning↑ →
            [+0.02,  0.0,  +0.02,  0.0,   0.0,  -0.06,  0.0,   0.0,   0.0 ],  # excite↑ →
            [ 0.0,  +0.02,  0.0,   0.0,  -0.06,  0.0,  +0.02,  0.0,   0.0 ],  # inhibit↑ →
            [-0.02,  0.0,  +0.03,  0.0,   0.0,  +0.03,  0.0,  -0.02, -0.02],  # stress↑ →
            [ 0.0,   0.0,   0.0,   0.0,   0.0,   0.0,  -0.02,  0.0,  +0.02],  # bonding↑ →
            [+0.02,  0.0,   0.0,   0.0,   0.0,   0.0,  -0.02, +0.02,  0.0 ],  # comfort↑ →
        ])
        # D: 자기 감쇠 계수 대각 행렬. 모든 원소 > 0.
        self.D = np.diag(np.full(9, 0.1))

    def update(self, experience_vector: np.ndarray) -> np.ndarray:
        """
        state(t+1) = state(t) + A × exp_vec + W × (state - baseline) + D × (baseline - state)
        - A: 외부 경험이 상태를 바꿈
        - W: 상태끼리 서로를 밀고 당김 (기저선 대비 편차에 비례)
        - D: 기저선으로 회귀
        """
        deviation = self.state - self.baselines
        delta = (self.A @ experience_vector
                 + self.W @ deviation
                 + self.D @ (self.baselines - self.state))
        # 변화율 제한: Δmax = 0.3
        delta = np.clip(delta, -0.3, 0.3)
        self.state = np.clip(self.state + delta, 0.0, 1.0)
        return self.state

    def validate_stability(self) -> bool:
        """야코비안 J = W - D의 고유값 실수부 전부 음수 확인 (점근적 안정성)"""
        jacobian = self.W - self.D
        eigenvalues = np.linalg.eigvals(jacobian)
        return all(ev.real < 0 for ev in eigenvalues)

    def apply_fast_path(self, state_changes: dict):
        """빠른 경로 즉시 상태 변경. Δmax 클램핑 + [0,1] 클램핑 적용."""
        for param, delta in state_changes.items():
            idx = self.PARAMS.index(param)
            clamped_delta = np.clip(delta, -0.3, 0.3)
            self.state[idx] = np.clip(self.state[idx] + clamped_delta, 0.0, 1.0)

    @staticmethod
    def experience_dict_to_vector(exp_dict: dict) -> np.ndarray:
        """경험 벡터 dict → numpy array. 차원 순서 = EXP_DIMS."""
        return np.array([exp_dict.get(dim, 0.0)
                         for dim in InternalState.EXP_DIMS])
```

- `experience_vector`: 5차원 `[reward, novelty, threat, social_reward, goal_progress]`
- extensions 차원이 추가되면 A에 열 추가, EXP_DIMS에 키 추가
- 매 턴 `pipeline.py`가 순서대로 호출: `fast_path → internal_state.update → drives.compute → emotion_base.update_raw_core_affect → self_sensing`

#### `emotion_base.py` — 코어 어펙트 + 기분

```python
class EmotionBase:
    def __init__(self, mood_decay_eta: float = 0.05,
                 negativity_weight: float = 0.6,
                 drive_alpha: float = 0.1, drive_gamma: float = 0.05):
        self.raw_core_affect = {'valence': 0.0, 'arousal': 0.0}   # 저수준 계산
        self.mood = {'valence': 0.0, 'arousal': 0.0}
        self.eta = mood_decay_eta         # 기분감쇠N에서 결정
        self.negativity_weight = negativity_weight  # 부정 편향 (기질 파라미터, 0.5~0.7)
        self.drive_alpha = drive_alpha    # 드라이브 결핍 → valence 계수
        self.drive_gamma = drive_gamma    # 드라이브 결핍 → arousal 계수

    def update_raw_core_affect(self, state: dict,
                               max_drive_deficit: float = 0.0) -> dict:
        """내부 상태 → raw 코어 어펙트 (저수준). meta_resource 참조 없음."""
        positive = (state['reward'] + state['comfort'] + state['bonding']) / 3.0
        negative = state['stress'] * self.negativity_weight
        raw_valence = (positive - negative) * 2.0 - 1.0
        raw_valence -= self.drive_alpha * max_drive_deficit

        raw_arousal = (
            (state['arousal'] + state['excitation']) / 2.0
            - (state['inhibition'] + state['patience']) / 2.0
        )
        raw_arousal += self.drive_gamma * max_drive_deficit

        self.raw_core_affect['valence'] = np.clip(raw_valence, -1.0, 1.0)
        self.raw_core_affect['arousal'] = np.clip(raw_arousal, 0.0, 1.0)
        return self.raw_core_affect

    def update_mood(self) -> dict:
        """mood(t) = mood(t-1) + η × (raw_core_affect(t) - mood(t-1)). mood는 raw 기반."""
        for dim in ['valence', 'arousal']:
            self.mood[dim] += self.eta * (self.raw_core_affect[dim] - self.mood[dim])
        return self.mood
```

> **인터페이스 보정 (interface/signal_rise.py에서 수행):**
> `final_valence = raw_valence - β × (1 - meta_resource)`. 고수준은 final_core_affect를 사용.

#### `pipeline.py` — 고정 실행 순서

```python
class LowLevelPipeline:
    def __init__(self, internal_state, emotion_base, drives, fast_path, self_sensing):
        self.internal_state = internal_state
        self.emotion_base = emotion_base
        self.drives = drives
        self.fast_path = fast_path
        self.self_sensing = self_sensing

    def run(self, raw_input: str, prev_experience: dict) -> dict:
        """매 턴 시작 전 고정 순서 실행 (1→2→3→4→5). 오케스트레이터 없이도 독립 작동."""
        # 1. 빠른 경로 체크
        fast_result = self.fast_path.check(raw_input)
        if fast_result:
            self.internal_state.apply_fast_path(fast_result)

        # 2. 내부 상태 업데이트 (이전 턴 경험 벡터 반영)
        exp_vec = InternalState.experience_dict_to_vector(prev_experience)
        state = self.internal_state.update(exp_vec)
        state_dict = dict(zip(self.internal_state.PARAMS, state))

        # 3. 드라이브 충족도 계산
        drive_status = self.drives.compute(state_dict)
        max_deficit = max(drive_status.get('deficits', {}).values(), default=0.0)

        # 4. 감정 기저 업데이트 (raw 코어 어펙트에 max_deficit 필요 → 3번 이후)
        raw_core_affect = self.emotion_base.update_raw_core_affect(state_dict, max_deficit)
        mood = self.emotion_base.update_mood()

        # 5. 자기감지
        self_signal = self.self_sensing.generate(state_dict, drive_status, raw_core_affect)

        return {
            'state': state_dict,
            'raw_core_affect': raw_core_affect,
            'mood': mood,
            'drives': drive_status,
            'self_signal': self_signal,
            'fast_path_triggered': fast_result is not None
        }
```

### 3.2 이벤트 버스 (`core/event_bus.py`)

```python
import asyncio
from dataclasses import dataclass, field
from typing import Callable, Any

@dataclass
class Event:
    name: str
    data: dict
    source: str
    timestamp: int  # 턴 번호

class EventBus:
    def __init__(self):
        self._subscribers: dict[str, list[Callable]] = {}
        self._sync_points: dict[str, SyncPoint] = {}

    def subscribe(self, event_name: str, handler: Callable):
        self._subscribers.setdefault(event_name, []).append(handler)

    async def publish(self, event: Event):
        for handler in self._subscribers.get(event.name, []):
            await handler(event)
        # 동기화 지점 업데이트
        for sp in self._sync_points.values():
            sp.receive(event.name, event.data)

    def create_sync_point(self, name: str, wait_for: list[str],
                          then: str, timeout_ms: int = 5000) -> 'SyncPoint':
        sp = SyncPoint(name, wait_for, then, timeout_ms)
        self._sync_points[name] = sp
        return sp

@dataclass
class SyncPoint:
    name: str
    wait_for: list[str]
    then: str
    timeout_ms: int
    received: dict = field(default_factory=dict)

    def receive(self, event_name: str, data: dict):
        if event_name in self.wait_for:
            self.received[event_name] = data

    @property
    def ready(self) -> bool:
        return all(e in self.received for e in self.wait_for)

    def consume(self) -> dict:
        """동기화 완료 시 수집된 데이터 반환 후 초기화"""
        data = dict(self.received)
        self.received.clear()
        return data
```

### 3.3 고수준 처리 흐름 (`high_level/`)

#### 1턴 처리 시퀀스 (오케스트레이터가 조율)

```python
async def process_conversation_turn(self, user_input: str, turn_number: int):
    """대화 턴 전체 파이프라인"""

    # 0. 저수준 파이프라인 (동기, 빠름)
    low_result = self.low_level.run(user_input, self.prev_experience)

    # 1. 감정 평가 (작은 모델, ~수백ms)
    try:
        emotion_result = await self.emotion_appraisal.evaluate(
            user_input, low_result['raw_core_affect']
        )
    except LLMError:
        emotion_result = self._emotion_fallback(low_result['raw_core_affect'])
    await self.event_bus.publish(Event('emotion_appraised', emotion_result, 'emotion', turn_number))

    # 1.5 자동 부호화 (감정 평가 직후, 고수준에서 수행)
    emotion_intensity = abs(emotion_result['valence']) + emotion_result['arousal']
    if emotion_intensity > self.auto_encoding_threshold:
        await self.storage.auto_encode(user_input, emotion_result, turn_number)

    # 2. 사회인지 ‖ 기억 인출 — 병렬
    social_task = self.social_cognition.evaluate(
        user_input, self.other_model, emotion_result
    )
    memory_task = self.memory_retrieval.retrieve(
        user_input, emotion_result, low_result['mood'], low_result['raw_core_affect']
    )
    social_result, memory_result = await asyncio.gather(social_task, memory_task)

    await self.event_bus.publish(Event('other_model_updated', social_result, 'social', turn_number))
    await self.event_bus.publish(Event('memory_retrieved', memory_result, 'memory', turn_number))

    # ▼ 동기화 지점: 경험 벡터 합성
    experience_vector = self.interface.assemble_experience(
        emotion_result, social_result, self.metacognition.goal_progress
    )

    # 메타인지 검토: 재평가 여부
    reappraisal = self.metacognition.review(
        emotion_result, social_result, low_result
    )
    if reappraisal.needs_reappraisal and reappraisal.iterations < 3:
        emotion_result = await self.emotion_appraisal.reappraise(
            emotion_result, reappraisal.strategy
        )
        experience_vector = self.interface.assemble_experience(
            emotion_result, social_result, self.metacognition.goal_progress
        )

    # 경험 벡터 → 저수준 전달 (다음 턴 시작 시 반영)
    self.prev_experience = experience_vector

    # 3. 후보 생성 (큰 모델)
    marker_signal = self.interface.signal_rise(low_result)
    candidates = await self.candidate_generation.generate(
        emotion_result, social_result, memory_result,
        self.self_model, low_result['mood'], marker_signal
    )

    # 4. 최종 판단 (큰 모델)
    response = await self.final_judgment.select(
        candidates, marker_signal, self.metacognition.confidence
    )

    # 5. 출력 후처리 (인터페이스 보정된 final_core_affect 사용)
    final_core_affect = self.interface.apply_meta_correction(
        low_result['raw_core_affect'], self.metacognition.resource
    )
    final_response = await self.output_postprocess.process(
        response, final_core_affect
    )

    # 스토리지 업데이트 (턴 종료)
    await self.storage.commit_turn(
        user_input, final_response, emotion_result,
        experience_vector, turn_number
    )

    return final_response

def _emotion_fallback(self, raw_core_affect: dict) -> dict:
    """LLM 실패 시 저수준 raw_core_affect 기반 최소 감정 결과 생성."""
    return {
        'valence': raw_core_affect['valence'],
        'arousal': raw_core_affect['arousal'],
        'preliminary_labels': [],
        'experience_dimensions': {
            'reward': max(0.0, raw_core_affect['valence']),
            'threat': max(0.0, -raw_core_affect['valence']),
            'novelty': 0.0,  # LLM 없이는 novelty 판단 불가
        }
    }
```

#### `interface/signal_rise.py` — `apply_meta_correction`

```python
def apply_meta_correction(self, raw_core_affect: dict,
                          meta_resource: float,
                          meta_beta: float = 0.08) -> dict:
    """raw_core_affect + 메타자원 보정 → final_core_affect. 인터페이스 계층."""
    final = dict(raw_core_affect)
    final['valence'] = np.clip(
        raw_core_affect['valence'] - meta_beta * (1.0 - meta_resource),
        -1.0, 1.0
    )
    return final
```

#### `storage/memory_store.py` — `auto_encode`

```python
async def auto_encode(self, user_input: str, emotion_result: dict,
                      turn_number: int):
    """감정 강도가 임계값을 넘는 입력을 자동 저장. 고수준에서 호출."""
    await self.store(
        content=user_input,  # 고수준이므로 주관적 요약도 가능하나, 초기엔 원문 저장
        emotion_tag={
            'valence': emotion_result['valence'],
            'arousal': emotion_result['arousal'],
            'labels': emotion_result.get('preliminary_labels', []),
        },
        source='experience',
        importance=min(1.0, abs(emotion_result['valence']) + emotion_result['arousal']),
        turn=turn_number,
    )
```

### 3.4 스토리지 (`storage/`)

#### `memory_store.py` — 기억 CRUD + 재고정화

```python
class EpisodicMemory:
    def __init__(self, vector_db: VectorDB, reconsolidation_alpha: float = 0.3):
        self.vector_db = vector_db
        self.alpha = reconsolidation_alpha  # 재고정화 블렌딩 비율

    async def store(self, content: str, emotion_tag: dict,
                    source: str, importance: float, turn: int):
        embedding = await self.vector_db.embed(content)
        self.vector_db.upsert({
            'id': uuid4(),
            'content': content,
            'embedding': embedding,
            'emotion_tag': emotion_tag,
            'source': source,
            'importance': importance,
            'retrieval_count': 0,
            'last_retrieved': turn,
            'reconsolidated': False,
            'timestamp': turn
        })

    async def retrieve(self, query: str, mood: dict,
                       core_affect: dict, k: int = 5) -> list[dict]:
        results = await self.vector_db.search(
            query=query,
            k=k * 2,  # 재순위 여유분
            mood_bias=mood  # 기분 일치 인출 편향 (mood가 어떤 기억이 올라오는지 결정)
        )
        # 출처 우선순위: experience > internet > general >> imagination
        results = self._apply_source_priority(results)
        # 상위 K개
        results = results[:k]
        # 재고정화: 인출 시점의 코어 어펙트로 감정 태그 블렌딩
        # mood ≠ core_affect: 인출 편향은 mood, 재고정화는 core_affect
        for mem in results:
            self._reconsolidate(mem, core_affect)
        return results

    def _reconsolidate(self, memory: dict, core_affect: dict):
        """new_tag = α × core_affect + (1-α) × original"""
        orig = memory['emotion_tag']
        memory['emotion_tag'] = {
            'valence': self.alpha * core_affect['valence']
                       + (1 - self.alpha) * orig['valence'],
            'arousal': self.alpha * core_affect['arousal']
                       + (1 - self.alpha) * orig['arousal'],
            'labels': orig['labels']  # 라벨은 유지
        }
        memory['retrieval_count'] += 1
        memory['reconsolidated'] = True
        self.vector_db.update(memory['id'], memory)
```

#### `snapshot.py` — 턴 기반 잠금

```python
class SnapshotManager:
    """턴 기반 잠금: 저수준 처리 → 스냅샷 고정 → 고수준 읽기 → 쓰기 일괄 적용"""

    def __init__(self, storage):
        self.storage = storage
        self._pending_writes: list[dict] = []
        self._snapshot: dict = {}

    def freeze(self):
        """저수준 처리 완료 후 스냅샷 고정"""
        self._snapshot = self.storage.get_current_state()
        self._pending_writes.clear()

    def read(self, key: str):
        """고수준은 스냅샷에서만 읽기"""
        return self._snapshot.get(key)

    def stage_write(self, key: str, value: dict):
        """쓰기는 스테이징만"""
        self._pending_writes.append((key, value))

    def commit(self):
        """턴 종료 시 일괄 적용"""
        for key, value in self._pending_writes:
            self.storage.write(key, value)
        self._pending_writes.clear()

    def rollback(self):
        """DMN 중단 시"""
        self._pending_writes.clear()
```

### 3.5 인터페이스 (`interface/`)

#### `signal_rise.py` — 정밀도 손실 적용

```python
class SignalRise:
    """저수준 숫자 → 고수준 자연어 변환. 정밀도 손실 = 자기 인식 한계."""

    RESOLUTION_LEVELS = {
        2: ['없음', '있음'],
        3: ['낮음', '중간', '높음'],
        5: ['매우 낮음', '낮음', '중간', '높음', '매우 높음'],
    }

    def __init__(self, resolution: int = 3):
        self.resolution = resolution
        self.labels = self.RESOLUTION_LEVELS[resolution]

    def quantize(self, value: float, param_name: str) -> str:
        """0.0~1.0 → 자연어 라벨 (해상도에 따른 정밀도 손실)"""
        idx = min(int(value * self.resolution), self.resolution - 1)
        return f"{param_name}이(가) {self.labels[idx]}"

    def generate_self_signal(self, state: dict, drives: dict,
                             core_affect: dict) -> str:
        """내부 상태 전체를 자연어 자기감지 신호로 변환"""
        signals = []
        for param, value in state.items():
            signals.append(self.quantize(value, param))
        # 코어 어펙트
        valence_word = "긍정적" if core_affect['valence'] > 0 else "부정적"
        signals.append(f"전반적 기분이 {valence_word}")
        return ". ".join(signals)
```

#### `experience_descent.py` — 경험 벡터 조립

```python
class ExperienceDescent:
    """고수준 평가 결과 → 저수준 경험 벡터"""

    def assemble(self, emotion_result: dict, social_result: dict,
                 goal_progress: float | None = None) -> dict:
        """
        각 모듈이 자기 영역 차원만 채움 (단일 생성자 아님).
        감정평가 → reward, threat, novelty
        사회인지 → social_reward
        메타인지 → goal_progress (있을 때만)
        """
        vec = {
            'reward': np.clip(emotion_result['experience_dimensions']['reward'], 0.0, 1.0),
            'threat': np.clip(emotion_result['experience_dimensions']['threat'], 0.0, 1.0),
            'novelty': np.clip(emotion_result['experience_dimensions']['novelty'], 0.0, 1.0),
            'social_reward': np.clip(social_result['social_reward'], 0.0, 1.0),
            'goal_progress': np.clip(goal_progress or 0.0, 0.0, 1.0),
            'extensions': {}
        }
        return vec
```

#### `schemas.py` — 이벤트 스키마 (Pydantic)

```python
from pydantic import BaseModel, Field

class ExperienceDimensions(BaseModel):
    reward: float  = Field(ge=0.0, le=1.0)
    threat: float  = Field(ge=0.0, le=1.0)
    novelty: float = Field(ge=0.0, le=1.0)

class EmotionAppraised(BaseModel):
    valence: float               = Field(ge=-1.0, le=1.0)
    arousal: float               = Field(ge=0.0, le=1.0)
    preliminary_labels: list[str]  # 초벌 감정 라벨 (Barrett TCE "예측 먼저")
    experience_dimensions: ExperienceDimensions

class OtherModelUpdated(BaseModel):
    person_id: str
    estimated_emotion: dict  # {valence, arousal}
    estimated_intent: str
    social_reward: float = Field(ge=0.0, le=1.0)

class MemoryItem(BaseModel):
    id: str
    content: str
    emotion_tag: dict
    importance: float = Field(ge=0.0, le=1.0)

class ProspectiveItem(BaseModel):
    id: str
    content: str
    priority: float = Field(ge=0.0, le=1.0)

class MemoryRetrieved(BaseModel):
    memories: list[MemoryItem]
    prospective_items: list[ProspectiveItem]
    retrieval_context: dict   # {mood_bias_applied: bool}
```

---

## 4. 설정 파일 형식

### `config/temperament_default.yaml`

```yaml
# 기질 파라미터 — "같은 코드, 다른 기저선 → 다른 사람"
name: "default"
description: "기본 기질 프로필"

# 내부 상태 기저선 (9개, 0.0~1.0)
baselines:
  reward: 0.5
  patience: 0.5
  arousal: 0.4
  learning: 0.5
  excitation: 0.4
  inhibition: 0.5
  stress: 0.2
  bonding: 0.3
  comfort: 0.5

# DMN 활성도 (유휴 시 기본)
dmn_activity: 0.5

# 메타인지
metacognition_sensitivity: 0.5   # 모니터링 민감도
metacognition_floor: 0.1         # 자원 바닥 (완전 고갈 방지)
meta_resource_recovery: 0.05     # 턴당 회복률
emotion_regulation_capacity: 0.5 # 감정 조절 효과 크기

# 경험 마커
marker_inertia: 50               # 마커 지속 턴 수

# 자기 인식
self_awareness_resolution: 3     # 신호 상승 정밀도 (2/3/5 단계)

# 서사
narrative_pressure: 0.5          # 자기 서사 구축 경향

# 드라이브 비율
drive_ratios:
  curiosity: 0.25
  bonding: 0.25
  preservation: 0.15
  safety: 0.15
  pleasure: 0.20

# 관계
relationship_threshold: 100      # 관계 단계 전환 bonding 누적량 (턴)

# 기분
mood_decay_eta: 0.05             # leaky integral 감쇠율 (N=20~50턴에 대응)

# 기질 표류
temperament_drift_beta: 0.0002   # 1/K, K=5000
temperament_drift_gamma: 0.001   # 표류 속도

# 재고정화
reconsolidation_alpha: 0.3       # new_tag = α×current + (1-α)×original

# 코어 어펙트 보정 계수
negativity_weight: 0.6           # stress의 valence 영향 가중치 (0.5~0.7)
drive_alpha: 0.1                 # 드라이브 결핍 → valence 계수
drive_gamma: 0.05                # 드라이브 결핍 → arousal 계수
meta_beta: 0.08                  # 메타자원 고갈 → valence 계수 (인터페이스 보정)

# 자동 부호화
auto_encoding_threshold: 1.2     # |valence| + arousal 임계값

# 빠른 경로
fast_path_confidence_threshold: 0.6  # 패턴 매칭 최소 confidence

# 경험 마커
marker_formation_threshold: 0.7  # reward/threat가 이 값 초과 시 마커 형성
marker_decay_rate: 0.01          # 정비 시 마커 strength 감쇠율
```

### `config/temperament_test.yaml`

```yaml
# 테스트 모드: 200턴이면 전체 라이프사이클 관찰 가능
name: "test"
description: "테스트 모드 — 시간 압축"

baselines:  # 기본과 동일
  reward: 0.5
  patience: 0.5
  arousal: 0.4
  learning: 0.5
  excitation: 0.4
  inhibition: 0.5
  stress: 0.2
  bonding: 0.3
  comfort: 0.5

# 시간 압축
mood_decay_eta: 0.2              # N=5턴
temperament_drift_beta: 0.01     # K=100턴
temperament_drift_gamma: 0.01    # 빠른 표류

# 나머지는 기본값과 동일
dmn_activity: 0.5
metacognition_sensitivity: 0.5
metacognition_floor: 0.1
meta_resource_recovery: 0.05
emotion_regulation_capacity: 0.5
marker_inertia: 10
self_awareness_resolution: 3
narrative_pressure: 0.5
drive_ratios:
  curiosity: 0.25
  bonding: 0.25
  preservation: 0.15
  safety: 0.15
  pleasure: 0.20
relationship_threshold: 20
reconsolidation_alpha: 0.3

# 코어 어펙트 보정 계수 (기본과 동일)
negativity_weight: 0.6
drive_alpha: 0.1
drive_gamma: 0.05
meta_beta: 0.08

# 자동 부호화 / 빠른 경로 / 마커 (기본과 동일)
auto_encoding_threshold: 1.2
fast_path_confidence_threshold: 0.6
marker_formation_threshold: 0.7
marker_decay_rate: 0.05          # 테스트 모드: 빠른 감쇠
```

### `config/models.yaml`

```yaml
# LLM 모델 설정
small_model:
  provider: "anthropic"       # anthropic | openai | ollama
  model: "claude-haiku-4-5-20251001"
  max_tokens: 1024
  temperature: 0.7
  timeout_ms: 3000
  # 용도: 감정 평가, 사회인지, 톤 검증

large_model:
  provider: "anthropic"
  model: "claude-sonnet-4-6"
  max_tokens: 2048
  temperature: 0.8
  timeout_ms: 10000
  # 용도: 후보 생성, 최종 판단

dmn_model:
  provider: "anthropic"
  model: "claude-haiku-4-5-20251001"
  max_tokens: 1024
  temperature: 0.9            # DMN은 더 자유롭게
  timeout_ms: 5000
  # 용도: 반추, 사색, 사례 승격

# 구현 옵션 (최소/표준/풀)
call_config: "standard"       # minimum | standard | full
```

---

## 5. 구현 순서

가장 작은 루프부터. 각 단계가 독립적으로 테스트 가능해야 함.

### Phase 1: 저수준 파이프라인 단독

**목표:** LLM 없이 순수 수치 연산만으로 내부 상태 시뮬레이션.

- `internal_state.py`: 9 파라미터 + 상호작용 행렬 + 안정성 검증 + `apply_fast_path()`
- `emotion_base.py`: raw 코어 어펙트 계산 + 기분 leaky integral
- `drives.py`: 5 드라이브 충족도 + 결핍도 계산
- `markers.py`: 경험 마커 수치 관리 (형성/감쇠/갱신)
- `temperament.py`: YAML 로드 + EMA 표류
- `pipeline.py`: 고정 순서 실행
- `test_stability.py`: 행렬 고유값 검증, Δmax 클램핑 검증
- `test_drives.py`: 드라이브 충족도 공식 검증 (5개 드라이브 각각)
- `test_markers.py`: 마커 형성/감쇠/갱신 검증

**검증:** 경험 벡터를 수동으로 주입 → 상태 변화 관찰 → 200턴 시뮬레이션 → 발산/수렴 확인.

### Phase 2: 스토리지 + 기억

- `vector_db.py`: ChromaDB 래퍼 (임베딩, 검색, 메타데이터 필터)
- `memory_store.py`: 일화기억 CRUD + 재고정화 블렌딩 + 감쇠
- `self_model.py` / `other_model.py`: JSON 기반 모델 CRUD
- `snapshot.py`: 턴 기반 잠금
- `test_reconsolidation.py`: α 블렌딩 검증, 우울 나선 방지 검증

### Phase 3: 최소 대화 루프

- `emotion_appraisal.py`: 작은 모델 1개 연결
- `interface/`: 신호 상승 + 경험 하강
- `event_bus.py`: 인메모리 pub/sub
- 입력 → 감정 평가 → 경험 벡터 → 저수준 업데이트 → **최소 루프 완성**
- 아직 응답 생성 없음 — 상태 변화만 관찰

### Phase 4: 대화 가능 시스템

- `candidate_generation.py` + `final_judgment.py`: 큰 모델 연결
- `memory_retrieval.py`: 벡터 검색 + 감정 태그 교차
- `output_postprocess.py`: 톤 검증 + 응답 지연
- `main.py`: CLI 대화 루프
- **첫 번째 실제 대화 가능 시점**

### Phase 5: 완전한 시스템

- `social_cognition.py`: 사회인지 + 타자 모델 업데이트
- `metacognition.py`: 모니터링 + 통제 + 자원 관리 + 재평가 루프
- `dmn.py`: 우선순위 큐, 반추, 사례 승격, 지식 내면화
- `orchestrator.py` + `trigger_registry.py`: 턴 관리, 트리거 발동, 운용 모드
- `fast_path.py`: 패턴 매칭 + 즉시 상태 변경

### Phase 6: 검증 + 튜닝

- 27개 시나리오 테스트 구현
- 상호작용 행렬 A 계수 튜닝
- **W 행렬 계수 튜닝** (부호 방향은 명세 확정, 크기를 시나리오로 조정)
- 기질 파라미터 프로필 다양화
- 전체 라이프사이클 테스트 (테스트 모드 200턴)
- 성능 프로파일링 (LLM 호출 지연 측정)

---

## 6. 의존성

```
# pyproject.toml [dependencies]
numpy>=1.26
pydantic>=2.0
pyyaml>=6.0
chromadb>=0.5
litellm>=1.0          # 또는 anthropic + openai SDK 직접
aiohttp>=3.9
pytest>=8.0
pytest-asyncio>=0.23
```

---

## 7. 명세 ↔ 구현 매핑

| 명세 섹션 | 구현 파일 | 핵심 데이터 |
|---|---|---|
| 1. 시스템 레벨 | `core/orchestrator.py`, `core/trigger_registry.py`, `core/turn.py` | 턴 유형, 트리거 우선순위 |
| 2.1 이벤트 버스 | `core/event_bus.py`, `interface/schemas.py` | Event, SyncPoint |
| 2.2 처리 순서 ①~⑤ | `high_level/*.py` | 비동기 파이프라인 |
| 2.3 메타인지 | `high_level/metacognition.py` | 자원(float), floor, 전략 |
| 2.4 DMN | `high_level/dmn.py` | 우선순위 큐, 트랜잭션 |
| 2.5 빠른 경로 | `low_level/fast_path.py` | 패턴 DB (절차기억 하위) |
| 3. 인터페이스 | `interface/signal_rise.py`, `interface/experience_descent.py` | 정밀도 손실, 경험 벡터 |
| 4. 저수준 | `low_level/*.py` | NumPy 행렬, 9 파라미터 |
| 4.3.3 경험 마커 | `low_level/markers.py`, `storage/marker_store.py` | 접근/회피 태그, 감쇠/갱신 |
| 5. 스토리지 | `storage/*.py` | ChromaDB, SQLite, 스냅샷 |
| 6. 기질 | `config/*.yaml`, `low_level/temperament.py` | YAML 로드, EMA 표류 |
