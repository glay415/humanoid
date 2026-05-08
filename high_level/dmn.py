"""DMN (Default Mode Network) — 유휴 시 작동.

우선순위 큐 (높을수록 먼저):
  1. 미평가 입력 재처리 (감정 평가 폴백 큐)
  2. 반추 (강한 감정 태그 기억의 재해석, 반추 카운터로 과반추 방지)
  3. 사례 승격 (충분한 사례가 쌓인 절차기억 → 규칙 추상화)
  4. 지식 내면화 (새 의미기억 → 자기 서사 영향 평가)
  5. 사색 (드라이브 기반 자유 연상)

대화 중에는 LLM 호출 안 함. 대화 턴 시작 시 즉시 중단(미커밋 트랜잭션 롤백).
한 활동 = 단일 스토리지 항목에 대한 begin/commit/rollback (spec §2.4).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum


# ---------------------------------------------------------------------------
# 데이터 형태 — 다음 커밋의 구현이 사용하는 입력/출력 셰이프.
# ---------------------------------------------------------------------------


class DMNActivityType(IntEnum):
    """우선순위 큐의 활동 유형. 값이 작을수록 우선순위 높음."""
    UNAPPRAISED_REPROCESS = 1
    RUMINATE = 2
    CASE_PROMOTE = 3
    KNOWLEDGE_INTERNALIZE = 4
    CONTEMPLATE = 5


@dataclass
class DMNContext:
    """DMN 사이클이 읽는 입력. 없으면 해당 활동은 건너뛴다."""
    episodic: object | None = None        # storage.EpisodicMemory
    marker_store: object | None = None    # storage.MarkerStore
    self_model: object | None = None      # storage.SelfModel
    other_model: object | None = None     # storage.OtherModel
    snapshot_manager: object | None = None  # storage.SnapshotManager
    llm: object | None = None             # llm.LLMClient | MockLLMClient
    drives: dict | None = None            # {'fulfillment': {...}, 'deficits': {...}}
    unappraised_queue: list = field(default_factory=list)
    rumination_counter: dict = field(default_factory=dict)
    turn: int = 0


@dataclass
class DMNCycleResult:
    """DMN 사이클 1회 실행 결과."""
    activity: str
    activity_type: int
    success: bool
    output: dict
    committed: bool
    error: str | None = None


# ---------------------------------------------------------------------------
# DMN — 셰이프 정의. run_cycle 구현은 다음 커밋에서.
# ---------------------------------------------------------------------------


class DMN:
    """DMN 모듈. 셰이프만 정의 — run_cycle 구현은 다음 커밋."""

    def __init__(self, base_activity: float = 0.5, max_rumination_per_memory: int = 3):
        self.activity: float = base_activity  # 0~1 연속값
        self.max_rumination = max_rumination_per_memory
        self.unappraised_queue: list = []
        self.rumination_counter: dict[str, int] = {}

    async def run_cycle(self, ctx: DMNContext) -> DMNCycleResult | None:
        """DMN 사이클 1회 실행. 다음 커밋에서 구현."""
        raise NotImplementedError("Implementation in next commit")
