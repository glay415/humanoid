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
from typing import Callable

from llm.client import LLMError
from llm.prompts import load_prompt
from low_level.fast_path import FastPathPattern


def _noop_commit_sink(key: str, value: object) -> None:
    """기본 commit sink — 아무것도 하지 않는다 (Wave 7 호환)."""
    return None


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
    # ADR-015: 미평가 입력 retrospective 재평가용. None 이면 Activity 1 은
    # 종전대로 큐에서 pop 만 (LLM 콜 + delayed encoding 없이) — backward compat.
    emotion_appraisal: object | None = None  # high_level.EmotionAppraisal
    # ADR-018: 사례 승격 (Activity 2) 의 결과를 실제 fast_path 패턴으로 register.
    # None 이면 종전대로 텍스트 규칙 영속 (ADR-016) 까지만, 자동 경로 미생성.
    fast_path: object | None = None       # low_level.FastPath
    drives: dict | None = None            # {'fulfillment': {...}, 'deficits': {...}}
    unappraised_queue: list = field(default_factory=list)
    rumination_counter: dict = field(default_factory=dict)
    turn: int = 0
    # audit β6: 트랜잭션 commit 의 실제 영속화 sink.
    # SnapshotManager.commit(commit_sink) 가 stage 된 (key, value) 쌍 각각에 대해
    # 호출. None 또는 미설정 → 기본 no-op (Wave 7 동작 그대로).
    # 실제 영속화 백엔드 (예: 파일 기반 K-V 스토어) 를 hook 으로 주입할 때 사용.
    commit_sink: Callable[[str, object], None] | None = None


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

    async def run_cycle(
        self,
        ctx: DMNContext,
        max_activities: int = 2,
    ) -> list[DMNCycleResult]:
        """우선순위 큐 실행. spec §2.4 — 한 DMN 턴에 1~2개 활동 처리 (audit ε3).

        각 활동은 try-except 로 감싸 한 활동 실패가 다음 활동을 막지 않게 한다.
        활동이 LLM 에러로 인해 실패해도 DMNCycleResult(success=False) 가 들어
        간다. 자격 없는 활동은 None 을 반환하므로 그냥 건너뛴다.

        Returns:
            DMNCycleResult 의 리스트. 자격 있는 활동이 하나도 없으면 빈 리스트.
            ``max_activities`` 도달 시 즉시 종료. 기본값 2.
        """
        # ctx.unappraised_queue 와 ctx.rumination_counter 가 비어있으면 인스턴스 상태로 fallback.
        if not ctx.unappraised_queue and self.unappraised_queue:
            ctx.unappraised_queue = self.unappraised_queue
        if not ctx.rumination_counter and self.rumination_counter:
            ctx.rumination_counter = self.rumination_counter

        results: list[DMNCycleResult] = []
        for fn in (
            self._try_unappraised_reprocess,
            self._try_ruminate,
            self._try_case_promote,
            self._try_knowledge_internalize,
            self._try_contemplate,
        ):
            if len(results) >= max_activities:
                break
            try:
                result = await fn(ctx)
            except Exception:  # noqa: BLE001 — 한 활동 크래시가 사이클을 죽이지 않게.
                # 스냅샷 매니저가 있으면 안전하게 롤백.
                if ctx.snapshot_manager is not None:
                    try:
                        ctx.snapshot_manager.rollback()
                    except Exception:
                        pass
                # 다음 활동으로 계속 진행 (활동별 격리).
                continue
            if result is not None:
                results.append(result)
        return results

    # -------------------------------------------------------------- activity 1

    async def _try_unappraised_reprocess(self, ctx: DMNContext) -> DMNCycleResult | None:
        """ADR-014 의 미평가 큐 → ADR-015 의 retrospective LLM 재평가 + delayed encoding.

        흐름 (spec §2.4 우선순위 1):
          1. 큐에서 가장 오래된 항목 pop.
          2. ctx.emotion_appraisal + ctx.episodic 둘 다 있으면 LLM 재평가 후
             episodic.store(source='delayed_appraisal') 로 delayed encoding.
          3. 둘 중 하나라도 없으면 종전대로 flag-only (backward compat).
          4. LLM 재평가 실패: 항목 *drop* — 재큐잉 안 함 (무한 재시도 방지).

        대화 latency 영향 없음: 본 활동은 DMN/정비 턴에서만 실행 (spec §1.3
        turn priority: 대화 > DMN > 정비). 사용자 입력 있으면 트리거 안 됨.
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

        appraisal = getattr(ctx, 'emotion_appraisal', None)
        episodic = ctx.episodic
        # backward compat: 옵션 어느 한쪽이라도 없으면 종전 flag-only 동작.
        if appraisal is None or episodic is None:
            return DMNCycleResult(
                activity='unappraised_reprocess',
                activity_type=int(DMNActivityType.UNAPPRAISED_REPROCESS),
                success=True,
                output={'item': item, 'note': 'reprocessing flagged for orchestrator'},
                committed=False,
            )

        user_input = item.get('user_input', '') or ''
        raw_core_affect = item.get('raw_core_affect') or {}
        # spec §2.4: retrospective LLM 재평가 — emotion_appraisal 의 본 evaluate
        # 를 재사용한다 (별도 prompt 불필요).
        sm = ctx.snapshot_manager
        try:
            emotion_result = await appraisal.evaluate(
                user_input=user_input,
                raw_core_affect={
                    'valence': float(raw_core_affect.get('valence', 0.0)),
                    'arousal': float(raw_core_affect.get('arousal', 0.0)),
                },
            )
        except LLMError as exc:
            if sm is not None:
                try:
                    sm.rollback()
                except Exception:
                    pass
            return DMNCycleResult(
                activity='unappraised_reprocess',
                activity_type=int(DMNActivityType.UNAPPRAISED_REPROCESS),
                success=False,
                output={'item': item, 'note': 'retrospective LLM failed, item dropped'},
                committed=False,
                error=f'LLMError: {exc}',
            )

        # Delayed episodic encoding. source='delayed_appraisal' — 일반 turn 의
        # 'experience' 와 구분되되 우선순위는 동일 (storage.memory_store).
        try:
            mem_id = await episodic.store(
                content=user_input,
                emotion_tag={
                    'valence': float(emotion_result.get('valence', 0.0)),
                    'arousal': float(emotion_result.get('arousal', 0.0)),
                    'labels': list(emotion_result.get('preliminary_labels', [])),
                },
                source='delayed_appraisal',
                importance=min(1.0, abs(float(emotion_result.get('valence', 0.0)))
                               + float(emotion_result.get('arousal', 0.0))),
                turn=int(ctx.turn),
            )
        except Exception as exc:  # noqa: BLE001 — 인코딩 실패는 sub-error 로만.
            if sm is not None:
                try:
                    sm.rollback()
                except Exception:
                    pass
            return DMNCycleResult(
                activity='unappraised_reprocess',
                activity_type=int(DMNActivityType.UNAPPRAISED_REPROCESS),
                success=False,
                output={'item': item, 'note': 'delayed encoding failed'},
                committed=False,
                error=f'EncodingError: {exc!r}',
            )

        committed = False
        if sm is not None:
            try:
                sm.stage_write(f'delayed_appraisal:{mem_id}', {
                    'memory_id': mem_id,
                    'user_input': user_input,
                    'emotion': {
                        'valence': float(emotion_result.get('valence', 0.0)),
                        'arousal': float(emotion_result.get('arousal', 0.0)),
                        'labels': list(emotion_result.get('preliminary_labels', [])),
                    },
                    'source_item': item,
                })
                sm.commit(ctx.commit_sink or _noop_commit_sink)
                committed = True
            except Exception:
                try:
                    sm.rollback()
                except Exception:
                    pass

        return DMNCycleResult(
            activity='unappraised_reprocess',
            activity_type=int(DMNActivityType.UNAPPRAISED_REPROCESS),
            success=True,
            output={
                'item': item,
                'memory_id': mem_id,
                'emotion': {
                    'valence': float(emotion_result.get('valence', 0.0)),
                    'arousal': float(emotion_result.get('arousal', 0.0)),
                    'labels': list(emotion_result.get('preliminary_labels', [])),
                },
                'note': 'delayed encoding ok',
            },
            committed=committed,
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
                # audit β6: ctx.commit_sink 가 있으면 그 hook 으로 영속화.
                # 없으면 no-op (Wave 7 호환). SnapshotManager.commit 는
                # stage 된 (key, value) 각각에 대해 sink 를 호출한다.
                sm.commit(ctx.commit_sink or _noop_commit_sink)
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

        # ADR-018 / ADR-019 — state_changes / confidence 를 *먼저* derive 한 뒤
        # stage_write payload 에 포함시키고 (재시작 후 복원에 사용), 같은 값으로
        # fast_path 에 register. 영속과 in-memory register 가 1:1 정합.
        derived_valence = float(chosen.get('valence', 0.0))
        derived_strength = float(chosen.get('strength', 0.0))
        if derived_valence >= 0.0:
            derived_state_changes: dict[str, float] = {'bonding': 0.05, 'comfort': 0.03}
        else:
            derived_state_changes = {'stress': 0.05, 'inhibition': 0.03}
        derived_confidence = max(0.0, min(1.0, derived_strength))

        committed = False
        if sm is not None:
            try:
                sm.stage_write(f'case_promote:{chosen.get("pattern_id")}', {
                    'pattern_id': chosen.get('pattern_id'),
                    'rule_summary': rule,
                    # ADR-019 — 재시작 시 fast_path 복원에 필요한 정보.
                    'valence': derived_valence,
                    'strength': derived_strength,
                    'state_changes': dict(derived_state_changes),
                    'confidence': derived_confidence,
                })
                # audit β6: ctx.commit_sink 가 있으면 그 hook 으로 영속화.
                sm.commit(ctx.commit_sink or _noop_commit_sink)
                committed = True
            except Exception:
                try:
                    sm.rollback()
                except Exception:
                    pass

        # ADR-018 — 위에서 derive 한 state_changes / confidence 로 fast_path register.
        promoted = False
        try:
            if ctx.fast_path is not None and hasattr(ctx.fast_path, 'register_or_update'):
                trigger = str(chosen.get('pattern_id', '')).strip()
                if trigger:
                    pattern = FastPathPattern(
                        trigger=trigger,
                        state_changes=dict(derived_state_changes),
                        confidence=derived_confidence,
                    )
                    ctx.fast_path.register_or_update(pattern)
                    promoted = True
        except Exception:
            # 승격 실패도 silent — DMN 사이클 흐름 보호 (영속은 이미 됨).
            pass

        return DMNCycleResult(
            activity='case_promote',
            activity_type=int(DMNActivityType.CASE_PROMOTE),
            success=True,
            output={
                'pattern_id': chosen.get('pattern_id'),
                'rule_summary': (rule or '').strip(),
                'fast_path_promoted': promoted,
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
                # audit β6: ctx.commit_sink 가 있으면 그 hook 으로 영속화.
                sm.commit(ctx.commit_sink or _noop_commit_sink)
                committed = True
            except Exception:
                try:
                    sm.rollback()
                except Exception:
                    pass

        # ADR-017 — delta 를 실제 self_model.narrative 에 누적 적용.
        # 본 wiring 으로 다음 턴의 unified_response prompt 에 변화된 self_narrative
        # 가 자동 반영된다. self_model 이 None 이면 no-op (test stub 호환).
        narrative_applied = False
        try:
            if ctx.self_model is not None and hasattr(ctx.self_model, 'add_internalized_delta'):
                ctx.self_model.add_internalized_delta(delta)
                narrative_applied = True
        except Exception:
            # 적용 실패도 silent — DMN 사이클 흐름 보호. delta 자체는 이미 영속.
            pass

        return DMNCycleResult(
            activity='knowledge_internalize',
            activity_type=int(DMNActivityType.KNOWLEDGE_INTERNALIZE),
            success=True,
            output={
                'memory_id': mem_id,
                'narrative_delta': (delta or '').strip(),
                'narrative_applied': narrative_applied,
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
                # audit β6: ctx.commit_sink 가 있으면 그 hook 으로 영속화.
                sm.commit(ctx.commit_sink or _noop_commit_sink)
                committed = True
            except Exception:
                try:
                    sm.rollback()
                except Exception:
                    pass

        # ADR-020 — reflection 을 self_model.narrative 의 [혼잣말] section 에 누적.
        # Activity 3 의 외부 자극 → 자기이해 와 결이 다르므로 별도 section.
        # 다음 turn 의 unified_response prompt 의 {self_narrative} 에 자동 반영.
        contemplation_applied = False
        try:
            if ctx.self_model is not None and hasattr(ctx.self_model, 'add_contemplation'):
                ctx.self_model.add_contemplation(reflection or '')
                contemplation_applied = True
        except Exception:
            # 적용 실패도 silent — DMN 사이클 흐름 보호 (영속은 이미 됨).
            pass

        return DMNCycleResult(
            activity='contemplate',
            activity_type=int(DMNActivityType.CONTEMPLATE),
            success=True,
            output={
                'drive': chosen_drive,
                'reflection': (reflection or '').strip(),
                'contemplation_applied': contemplation_applied,
            },
            committed=committed,
        )
