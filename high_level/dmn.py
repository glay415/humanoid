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

from llm.client import LLMError
from llm.prompts import load_prompt


# ---------------------------------------------------------------------------
# 데이터 형태
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
# 시스템 메시지 (역할 지시)
# ---------------------------------------------------------------------------


_SYSTEM_RUMINATE = (
    "당신은 인지 아키텍처의 DMN(기본 모드 네트워크)이다. "
    "강한 감정 기억을 현재 시점에서 재해석한다. 한국어 한 줄로만 답하라."
)
_SYSTEM_CASE_PROMOTE = (
    "당신은 DMN의 사례 승격 모듈이다. 누적 사례에서 일반 규칙을 한 줄로 추상화한다."
)
_SYSTEM_INTERNALIZE = (
    "당신은 DMN의 지식 내면화 모듈이다. 새 지식이 자기 서사에 보탤 한 줄을 찾는다."
)
_SYSTEM_CONTEMPLATE = (
    "당신은 DMN의 사색 모듈이다. 결핍 드라이브를 단서로 자유 연상 한 줄을 적는다."
)


# ---------------------------------------------------------------------------
# DMN
# ---------------------------------------------------------------------------


class DMN:
    """DMN 모듈 — 유휴 시 우선순위 큐 1회 실행."""

    def __init__(self, base_activity: float = 0.5, max_rumination_per_memory: int = 3):
        self.activity: float = base_activity  # 0~1 연속값
        self.max_rumination = max_rumination_per_memory
        # 외부에서 채워주는 폴백 큐 (감정 평가 실패 시 orchestrator 가 push)
        self.unappraised_queue: list = []
        self.rumination_counter: dict[str, int] = {}

        # 프롬프트는 모듈 로드 시 1회만 캐시.
        self._tpl_ruminate = load_prompt('dmn_ruminate')
        self._tpl_case_promote = load_prompt('dmn_case_promote')
        self._tpl_internalize = load_prompt('dmn_internalize')
        self._tpl_contemplate = load_prompt('dmn_contemplate')

    # ------------------------------------------------------------------ cycle

    async def run_cycle(self, ctx: DMNContext) -> DMNCycleResult | None:
        """우선순위 큐 1회 실행. 자격 있는 활동이 없으면 None.

        각 활동은 try-except 로 감싸 한 활동 실패가 다음 활동을 막지 않게 한다.
        활동이 LLM 에러로 인해 실패해도 DMNCycleResult(success=False) 를 반환할 수 있다.
        그 경우에도 더 낮은 우선순위 활동으로 진행하지 않고 그 결과를 그대로 반환한다.
        """
        # ctx.unappraised_queue 와 ctx.rumination_counter 가 비어있으면 인스턴스 상태로 fallback.
        if not ctx.unappraised_queue and self.unappraised_queue:
            ctx.unappraised_queue = self.unappraised_queue
        if not ctx.rumination_counter and self.rumination_counter:
            ctx.rumination_counter = self.rumination_counter

        for fn in (
            self._try_unappraised_reprocess,
            self._try_ruminate,
            self._try_case_promote,
            self._try_knowledge_internalize,
            self._try_contemplate,
        ):
            try:
                result = await fn(ctx)
            except Exception as exc:  # noqa: BLE001 — 한 활동 크래시가 사이클을 죽이지 않게.
                # 스냅샷 매니저가 있으면 안전하게 롤백.
                if ctx.snapshot_manager is not None:
                    try:
                        ctx.snapshot_manager.rollback()
                    except Exception:
                        pass
                # 다음 활동으로 계속 진행 (활동별 격리).
                continue
            if result is not None:
                return result
        return None

    # -------------------------------------------------------------- activity 1

    async def _try_unappraised_reprocess(self, ctx: DMNContext) -> DMNCycleResult | None:
        """감정 평가 실패 폴백 큐를 팝. 실제 재평가는 orchestrator 가 한다.

        Wave 7 범위: 큐에서 가장 오래된 항목 pop + 결과로 표시만.
        """
        queue = ctx.unappraised_queue
        if not queue:
            return None
        item = queue.pop(0)
        # 인스턴스 상태와 동기화 (ctx 가 인스턴스 큐를 가리키지 않는 경우 대비)
        if self.unappraised_queue and self.unappraised_queue is not queue:
            try:
                self.unappraised_queue.pop(0)
            except IndexError:
                pass
        return DMNCycleResult(
            activity='unappraised_reprocess',
            activity_type=int(DMNActivityType.UNAPPRAISED_REPROCESS),
            success=True,
            output={'item': item, 'note': 'reprocessing flagged for orchestrator'},
            committed=False,
        )

    # -------------------------------------------------------------- activity 2

    async def _try_ruminate(self, ctx: DMNContext) -> DMNCycleResult | None:
        """강한 감정 기억 1개를 골라 재해석 통찰 한 줄 생성."""
        if ctx.episodic is None or ctx.llm is None:
            return None

        # 기억 인출 — 감정-가중 검색이 아니라 일반 retrieve. mood/core_affect 는 중립값.
        try:
            mems = await ctx.episodic.retrieve(
                query='강한 감정 기억',
                mood={'valence': 0.0, 'arousal': 0.0},
                core_affect={'valence': 0.0, 'arousal': 0.0},
                k=10,
            )
        except Exception:
            return None
        if not mems:
            return None

        # 강한 감정 필터: |valence| + arousal > 1.0
        def _emotion_strength(mem: dict) -> float:
            tag = mem.get('emotion_tag') or {}
            return abs(float(tag.get('valence', 0.0))) + float(tag.get('arousal', 0.0))

        strong = [m for m in mems if _emotion_strength(m) > 1.0]
        if not strong:
            return None

        # importance 기준 상위 3개로 좁힘
        strong.sort(key=lambda m: -float(m.get('importance', 0.0)))
        top3 = strong[:3]

        # 반추 카운터 가장 낮은 후보 선택. 동률이면 importance 높은 쪽.
        counter = ctx.rumination_counter
        eligible = [m for m in top3 if counter.get(m.get('id'), 0) < self.max_rumination]
        if not eligible:
            return None
        eligible.sort(key=lambda m: (counter.get(m.get('id'), 0), -float(m.get('importance', 0.0))))
        chosen = eligible[0]
        mem_id = chosen.get('id')

        tag = chosen.get('emotion_tag') or {}
        rendered = self._tpl_ruminate.render(
            memory_content=chosen.get('content', ''),
            memory_valence=tag.get('valence', 0.0),
            memory_arousal=tag.get('arousal', 0.0),
            turn=ctx.turn,
        )
        messages = [
            {'role': 'system', 'content': _SYSTEM_RUMINATE},
            {'role': 'user', 'content': rendered},
        ]

        # 트랜잭션 시작 (단일 스토리지 항목 = 이 기억의 카운터)
        sm = ctx.snapshot_manager
        try:
            insight = await ctx.llm.complete(messages, model_name='dmn_model')
        except LLMError as exc:
            if sm is not None:
                try:
                    sm.rollback()
                except Exception:
                    pass
            return DMNCycleResult(
                activity='ruminate',
                activity_type=int(DMNActivityType.RUMINATE),
                success=False,
                output={'memory_id': mem_id},
                committed=False,
                error=f'LLMError: {exc}',
            )

        # 카운터 +1
        counter[mem_id] = counter.get(mem_id, 0) + 1
        # 인스턴스 상태와 동기화
        if self.rumination_counter is not counter:
            self.rumination_counter[mem_id] = counter[mem_id]

        committed = False
        if sm is not None:
            try:
                sm.stage_write(f'rumination:{mem_id}', {
                    'memory_id': mem_id,
                    'count': counter[mem_id],
                    'insight': insight,
                })
                sm.commit(lambda k, v: None)  # Wave 7: in-memory only.
                committed = True
            except Exception:
                try:
                    sm.rollback()
                except Exception:
                    pass

        return DMNCycleResult(
            activity='ruminate',
            activity_type=int(DMNActivityType.RUMINATE),
            success=True,
            output={
                'memory_id': mem_id,
                'insight': (insight or '').strip(),
                'count_after': counter[mem_id],
            },
            committed=committed,
        )

    # -------------------------------------------------------------- activity 3

    async def _try_case_promote(self, ctx: DMNContext) -> DMNCycleResult | None:
        """강한 마커(strength > 0.7) 1개를 골라 규칙 한 줄로 추상화."""
        if ctx.marker_store is None or ctx.llm is None:
            return None
        try:
            markers = ctx.marker_store.load_all()
        except Exception:
            return None
        candidates = [m for m in (markers or []) if float(m.get('strength', 0.0)) > 0.7]
        if not candidates:
            return None
        # 가장 강한 마커부터.
        candidates.sort(key=lambda m: -float(m.get('strength', 0.0)))
        chosen = candidates[0]
        valence_sign = '접근' if float(chosen.get('valence', 0.0)) >= 0 else '회피'

        rendered = self._tpl_case_promote.render(
            pattern_id=chosen.get('pattern_id', ''),
            strength=chosen.get('strength', 0.0),
            valence_sign=valence_sign,
        )
        messages = [
            {'role': 'system', 'content': _SYSTEM_CASE_PROMOTE},
            {'role': 'user', 'content': rendered},
        ]

        sm = ctx.snapshot_manager
        try:
            rule = await ctx.llm.complete(messages, model_name='dmn_model')
        except LLMError as exc:
            if sm is not None:
                try:
                    sm.rollback()
                except Exception:
                    pass
            return DMNCycleResult(
                activity='case_promote',
                activity_type=int(DMNActivityType.CASE_PROMOTE),
                success=False,
                output={'pattern_id': chosen.get('pattern_id')},
                committed=False,
                error=f'LLMError: {exc}',
            )

        committed = False
        if sm is not None:
            try:
                sm.stage_write(f'case_promote:{chosen.get("pattern_id")}', {
                    'pattern_id': chosen.get('pattern_id'),
                    'rule_summary': rule,
                })
                sm.commit(lambda k, v: None)
                committed = True
            except Exception:
                try:
                    sm.rollback()
                except Exception:
                    pass

        return DMNCycleResult(
            activity='case_promote',
            activity_type=int(DMNActivityType.CASE_PROMOTE),
            success=True,
            output={
                'pattern_id': chosen.get('pattern_id'),
                'rule_summary': (rule or '').strip(),
            },
            committed=committed,
        )

    # -------------------------------------------------------------- activity 4

    async def _try_knowledge_internalize(self, ctx: DMNContext) -> DMNCycleResult | None:
        """internet/general 출처의 의미기억이 자기 서사에 줄 영향 한 줄 평가."""
        if ctx.episodic is None or ctx.self_model is None or ctx.llm is None:
            return None
        try:
            mems = await ctx.episodic.retrieve(
                query='새로 알게 된 지식',
                mood={'valence': 0.0, 'arousal': 0.0},
                core_affect={'valence': 0.0, 'arousal': 0.0},
                k=10,
            )
        except Exception:
            return None
        if not mems:
            return None
        candidates = [
            m for m in mems
            if m.get('source') in ('internet', 'general')
            and float(m.get('importance', 0.0)) >= 0.3
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda m: -float(m.get('importance', 0.0)))
        chosen = candidates[0]
        mem_id = chosen.get('id')

        narrative = ''
        try:
            narrative = ctx.self_model.to_dict().get('narrative', '')
        except Exception:
            narrative = ''

        rendered = self._tpl_internalize.render(
            memory_content=chosen.get('content', ''),
            self_narrative=narrative,
        )
        messages = [
            {'role': 'system', 'content': _SYSTEM_INTERNALIZE},
            {'role': 'user', 'content': rendered},
        ]

        sm = ctx.snapshot_manager
        try:
            delta = await ctx.llm.complete(messages, model_name='dmn_model')
        except LLMError as exc:
            if sm is not None:
                try:
                    sm.rollback()
                except Exception:
                    pass
            return DMNCycleResult(
                activity='knowledge_internalize',
                activity_type=int(DMNActivityType.KNOWLEDGE_INTERNALIZE),
                success=False,
                output={'memory_id': mem_id},
                committed=False,
                error=f'LLMError: {exc}',
            )

        committed = False
        if sm is not None:
            try:
                sm.stage_write(f'self_model.narrative_delta:{mem_id}', {
                    'memory_id': mem_id,
                    'narrative_delta': delta,
                })
                sm.commit(lambda k, v: None)
                committed = True
            except Exception:
                try:
                    sm.rollback()
                except Exception:
                    pass

        return DMNCycleResult(
            activity='knowledge_internalize',
            activity_type=int(DMNActivityType.KNOWLEDGE_INTERNALIZE),
            success=True,
            output={
                'memory_id': mem_id,
                'narrative_delta': (delta or '').strip(),
            },
            committed=committed,
        )

    # -------------------------------------------------------------- activity 5

    async def _try_contemplate(self, ctx: DMNContext) -> DMNCycleResult | None:
        """가장 결핍된 드라이브를 단서로 자유 연상 한 줄 생성."""
        if ctx.drives is None or ctx.llm is None:
            return None
        # drives 형태 두 가지 모두 지원:
        #   (A) {'fulfillment': {name: 0~1, ...}}
        #   (B) {'deficits': {name: 0~1, ...}}
        #   (C) flat {name: 0~1} 충족도
        deficits: dict[str, float] = {}
        if isinstance(ctx.drives.get('deficits'), dict):
            deficits = {k: float(v) for k, v in ctx.drives['deficits'].items()}
        elif isinstance(ctx.drives.get('fulfillment'), dict):
            for k, v in ctx.drives['fulfillment'].items():
                deficits[k] = max(0.0, 1.0 - float(v))
        else:
            for k, v in ctx.drives.items():
                if isinstance(v, (int, float)):
                    deficits[k] = max(0.0, 1.0 - float(v))
        if not deficits:
            return None
        chosen_drive = max(deficits.items(), key=lambda kv: kv[1])[0]
        # 충족도 — 결핍의 보수.
        chosen_fulfillment = max(0.0, 1.0 - deficits[chosen_drive])

        rendered = self._tpl_contemplate.render(
            drive=chosen_drive,
            fulfillment=chosen_fulfillment,
        )
        messages = [
            {'role': 'system', 'content': _SYSTEM_CONTEMPLATE},
            {'role': 'user', 'content': rendered},
        ]

        sm = ctx.snapshot_manager
        try:
            reflection = await ctx.llm.complete(messages, model_name='dmn_model')
        except LLMError as exc:
            if sm is not None:
                try:
                    sm.rollback()
                except Exception:
                    pass
            return DMNCycleResult(
                activity='contemplate',
                activity_type=int(DMNActivityType.CONTEMPLATE),
                success=False,
                output={'drive': chosen_drive},
                committed=False,
                error=f'LLMError: {exc}',
            )

        committed = False
        if sm is not None:
            try:
                sm.stage_write(f'contemplate:{chosen_drive}', {
                    'drive': chosen_drive,
                    'reflection': reflection,
                })
                sm.commit(lambda k, v: None)
                committed = True
            except Exception:
                try:
                    sm.rollback()
                except Exception:
                    pass

        return DMNCycleResult(
            activity='contemplate',
            activity_type=int(DMNActivityType.CONTEMPLATE),
            success=True,
            output={
                'drive': chosen_drive,
                'reflection': (reflection or '').strip(),
            },
            committed=committed,
        )
