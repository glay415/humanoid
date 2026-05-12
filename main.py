"""humanoid — 인지 아키텍처 v12 진입점.

Phase 1: 저수준 파이프라인 단독 실행 (CLI, HUMANOID_MODE=low).
Phase 4~: 대화 루프 (CLI, HUMANOID_MODE=dialogue, default).
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from low_level.internal_state import InternalState
from low_level.emotion_base import EmotionBase
from low_level.drives import Drives
from low_level.markers import MarkerRegistry
from low_level.fast_path import FastPath
from low_level.self_sensing import SelfSensing
from low_level.temperament import Temperament
from low_level.pipeline import LowLevelPipeline
from core.event_bus import EventBus
from core.trigger_registry import TriggerRegistry
from core.orchestrator import Orchestrator
from interface.signal_rise import SignalRise
from interface.experience_descent import ExperienceDescent


CONFIG_DIR = Path(__file__).parent / 'config'


def build_low_level(config_path: Path | str | None = None) -> LowLevelPipeline:
    """저수준 파이프라인 조립. 기질 YAML에서 파라미터 로드."""
    if config_path is None:
        config_path = CONFIG_DIR / 'temperament_default.yaml'

    temperament = Temperament(config_path)
    cfg = temperament.config

    internal_state = InternalState(
        temperament.baselines,
        reactivity_vector=temperament.reactivity_vector(),
    )
    assert internal_state.validate_stability(), "W-D 행렬 안정성 검증 실패!"

    emotion_base = EmotionBase(
        mood_decay_eta=cfg.get('mood_decay_eta', 0.05),
        negativity_weight=cfg.get('negativity_weight', 0.6),
        drive_alpha=cfg.get('drive_alpha', 0.1),
        drive_gamma=cfg.get('drive_gamma', 0.05),
    )
    drives = Drives(drive_ratios=cfg['drive_ratios'])
    # ADR-024 — yaml 의 marker_inertia (0~100 scale, 일반적으로 40~50) 를
    # reinforcement_weight (0~1) 로 변환. weight = clamp(1 - inertia/100, 0.05, 0.95).
    # inertia=50 → weight=0.5 (default 0.3 보다 응답성 ↑), inertia=70 → 0.3 (legacy 동작).
    # yaml 에 marker_inertia 가 없으면 None → Marker.reinforce default 0.3 그대로.
    _marker_inertia = cfg.get('marker_inertia')
    _reinforcement_weight: float | None = None
    if _marker_inertia is not None:
        try:
            _reinforcement_weight = max(0.05, min(0.95, 1.0 - float(_marker_inertia) / 100.0))
        except (TypeError, ValueError):
            _reinforcement_weight = None
    markers = MarkerRegistry(
        formation_threshold=cfg.get('marker_formation_threshold', 0.7),
        decay_rate=cfg.get('marker_decay_rate', 0.01),
        reinforcement_weight=_reinforcement_weight,
    )
    fast_path = FastPath(
        confidence_threshold=cfg.get('fast_path_confidence_threshold', 0.6),
    )
    self_sensing = SelfSensing()

    return LowLevelPipeline(
        internal_state=internal_state,
        emotion_base=emotion_base,
        drives=drives,
        markers=markers,
        fast_path=fast_path,
        self_sensing=self_sensing,
        temperament=temperament,
    )


def build_orchestrator(
    config_path: Path | str | None = None,
) -> Orchestrator:
    """오케스트레이터 조립 — Phase 1 호환 (저수준 + 인터페이스만)."""
    low_level = build_low_level(config_path)
    cfg = low_level.temperament.config

    return Orchestrator(
        low_level=low_level,
        event_bus=EventBus(),
        trigger_registry=TriggerRegistry(),
        signal_rise=SignalRise(
            resolution=cfg.get('self_awareness_resolution', 3),
            meta_beta=cfg.get('meta_beta', 0.08),
        ),
        experience_descent=ExperienceDescent(),
        auto_encoding_threshold=cfg.get('auto_encoding_threshold', 1.2),
    )


def build_full_orchestrator(
    config_path: Path | str | None = None,
    llm_client=None,
    storage_root: Path | str | None = None,
) -> Orchestrator:
    """Phase 4: 모든 고수준 모듈 + 스토리지를 조립한 오케스트레이터.

    config_path: 기질 YAML. None 이면 default.
    llm_client: 테스트에서 MockLLMClient 주입용. None 이면 LLMClient() 생성.
    storage_root: 인스턴스별 디스크 격리용. 주어지면 ChromaDB / SQLite 가
        모두 storage_root 하위로 들어간다.
        - chroma_dir = storage_root / 'chroma_db'
        - prospective_db = storage_root / 'prospective.db'
        None 이면 기존 동작 — 기질 이름별 글로벌 디렉토리.
    """
    # 지연 import — 모듈 임포트 시점에 chroma/litellm 로드를 강제하지 않는다.
    from llm.client import LLMClient
    from high_level.emotion_appraisal import EmotionAppraisal
    from high_level.social_cognition import SocialCognition
    from high_level.memory_retrieval import MemoryRetrieval
    from high_level.candidate_generation import CandidateGeneration
    from high_level.final_judgment import FinalJudgment
    from high_level.output_postprocess import OutputPostprocess
    from high_level.metacognition import Metacognition
    from high_level.dmn import DMN
    from high_level.introspection import Introspection
    from storage.vector_db import VectorDB
    from storage.memory_store import EpisodicMemory
    from storage.prospective import ProspectiveQueue
    from storage.self_model import SelfModel
    from storage.other_model import OtherModel
    from storage.introspection_log import IntrospectionLogger
    from storage.dmn_artifacts import DMNArtifactStore

    low_level = build_low_level(config_path)
    cfg = low_level.temperament.config
    name = cfg.get('name', 'default')

    # LLM 클라이언트 — None 이면 실제 OpenAI 클라이언트 (LLMClient) 생성
    if llm_client is None:
        llm_client = LLMClient()

    # 스토리지 경로 결정
    if storage_root is not None:
        root = Path(storage_root)
        root.mkdir(parents=True, exist_ok=True)
        chroma_dir = str(root / 'chroma_db')
        prospective_db = str(root / 'prospective.db')
        dmn_artifacts_db = str(root / 'dmn_artifacts.db')
    else:
        # 기존 동작: 기질 이름별 글로벌 분리
        chroma_dir = f"./chroma_db/humanoid_{name}"
        storage_dir = Path(f"./storage_data/{name}")
        storage_dir.mkdir(parents=True, exist_ok=True)
        prospective_db = str(storage_dir / "prospective.db")
        dmn_artifacts_db = str(storage_dir / "dmn_artifacts.db")

    vector_db = VectorDB(
        collection_name=f"episodic_{name}",
        persist_dir=chroma_dir,
    )
    episodic = EpisodicMemory(
        vector_db=vector_db,
        reconsolidation_alpha=cfg.get('reconsolidation_alpha', 0.3),
    )
    prospective = ProspectiveQueue(db_path=prospective_db)
    # ADR-016 — DMN 활동 산출물 SQLite 영속화 (반추 통찰 / 일반 규칙 /
    # 자기 서사 델타 / 사색 텍스트 / delayed appraisal). orchestrator 가
    # DMNContext.commit_sink 로 wiring.
    dmn_artifacts = DMNArtifactStore(db_path=dmn_artifacts_db)

    # 고수준 모듈
    emotion_appraisal = EmotionAppraisal(llm_client=llm_client)
    social_cognition = SocialCognition()
    memory_retrieval = MemoryRetrieval(
        episodic=episodic,
        prospective=prospective,
    )
    candidate_generation = CandidateGeneration(llm_client=llm_client)
    final_judgment = FinalJudgment(llm_client=llm_client)
    output_postprocess = OutputPostprocess(llm_client=llm_client)
    # ADR-012 v1: final_judgment + output_postprocess 의 직렬 2~3 LLM 콜을 1콜로 합친
    # 통합 경로. 프로덕션 기본. 미지정 (None) 으로 빌드하면 legacy 2~3콜 경로 사용.
    from high_level.judge_finalize import JudgeFinalize
    judge_finalize = JudgeFinalize(llm_client=llm_client)
    # ADR-012 v2: emotion + candidate + judge_finalize 직렬 ~26s 를 단일 stream
    # LLM 콜로 단축 — ChatGPT-like UX. SSE 가 orch.stream_unified_turn 호출.
    from high_level.unified_response import UnifiedResponse
    unified_response = UnifiedResponse(llm_client=llm_client)
    metacognition = Metacognition(
        sensitivity=cfg.get('metacognition_sensitivity', 0.5),
        floor=cfg.get('metacognition_floor', 0.1),
        recovery_rate=cfg.get('meta_resource_recovery', 0.05),
        regulation_capacity=cfg.get('emotion_regulation_capacity', 0.5),
    )

    # DMN — 시그니처는 Team O 가 확정. 방어적으로 base_activity 만 전달.
    # ADR-027 — yaml 의 'dmn_activity' (페르소나별 DMN 활성도, 예: ENFP 0.7, ISTJ 0.4)
    # 가 모든 persona yaml 에 있지만 main 이 'dmn_base_activity' 로 찾는 키 미스매치로
    # 무시되던 갭. 둘 다 fallback 으로 받되 yaml 의 'dmn_activity' 가 정식.
    dmn = DMN(base_activity=cfg.get('dmn_activity', cfg.get('dmn_base_activity', 0.5)))
    # LLM 핸들 부착 — Team O 의 run_cycle 이 ctx.llm 으로도 받지만 호환을 위해.
    if not hasattr(dmn, 'llm') or getattr(dmn, 'llm', None) is None:
        try:
            dmn.llm = llm_client
        except AttributeError:
            pass

    # ADR-030: yaml 의 narrative_pressure 가 SelfModel 의 section cap (max_lines)
    # 을 결정. 미설정 시 default 0.5 → cap 5 (기존 동작).
    self_model = SelfModel(
        narrative_pressure=cfg.get('narrative_pressure', 0.5),
    )
    # ADR-030: yaml 의 relationship_threshold (E=70, I=130 등) 가 OtherModel 의
    # relationship_stage 전환 임계. 미설정 시 100 (neutral).
    other_model = OtherModel(
        relationship_threshold=int(cfg.get('relationship_threshold', 100)),
    )

    # 비동기 자기 분석 — 매 turn 끝의 background 일기 쓰기.
    # storage_root 가 주어진 경우에만 logger 동봉 (인스턴스 격리). 없으면 introspection
    # 모듈만 만들고 logger 는 None — 외부 (UI backend) 가 set 할 여지를 둔다.
    introspection = Introspection(llm_client=llm_client)
    if storage_root is not None:
        introspection_logger = IntrospectionLogger(Path(storage_root))
    else:
        introspection_logger = None

    orch = Orchestrator(
        low_level=low_level,
        event_bus=EventBus(),
        trigger_registry=TriggerRegistry(),
        signal_rise=SignalRise(
            resolution=cfg.get('self_awareness_resolution', 3),
            meta_beta=cfg.get('meta_beta', 0.08),
        ),
        experience_descent=ExperienceDescent(),
        auto_encoding_threshold=cfg.get('auto_encoding_threshold', 1.2),
        emotion_appraisal=emotion_appraisal,
        social_cognition=social_cognition,
        memory_retrieval=memory_retrieval,
        candidate_generation=candidate_generation,
        final_judgment=final_judgment,
        output_postprocess=output_postprocess,
        judge_finalize=judge_finalize,
        unified_response=unified_response,
        metacognition=metacognition,
        dmn=dmn,
        episodic_memory=episodic,
        self_model=self_model,
        other_model=other_model,
        introspection=introspection,
        introspection_logger=introspection_logger,
        persona_id=str(name),
        dmn_artifacts=dmn_artifacts,
    )
    orch.register_default_triggers()

    # ADR-019 — 인스턴스 재시작 시 dmn_artifacts.db 의 case_promote history 에서
    # fast_path 패턴 복원. 첫 spawn 시엔 store 가 비어 있어 no-op. 재시작 후에는
    # 이전 세션의 학습된 자동 경로가 살아나 spec §4.2 절차기억 동작 영속화.
    if low_level.fast_path is not None:
        try:
            rows = dmn_artifacts.latest_case_promotes()
            from low_level.fast_path import FastPathPattern as _FPP
            restored_count = 0
            for r in rows:
                payload = r.get('payload') or {}
                trigger = str(payload.get('pattern_id', '')).strip()
                state_changes = payload.get('state_changes')
                confidence = payload.get('confidence')
                if not trigger or not isinstance(state_changes, dict) or confidence is None:
                    continue  # ADR-019 이전 row (필드 누락) — skip.
                low_level.fast_path.register_or_update(
                    _FPP(
                        trigger=trigger,
                        state_changes=dict(state_changes),
                        confidence=float(confidence),
                    )
                )
                restored_count += 1
            if restored_count > 0:
                orch._log_event_safe('fast_path_restored', {
                    'count': restored_count,
                })
        except Exception:
            # best-effort — 복원 실패가 새 인스턴스 빌드를 막지 않게.
            pass

    # ADR-028 — marker registry 복원. ADR-022 의 marker 형성 hook 이 매 turn
    # snapshot 영속하므로 재시작 시 그 latest 상태 그대로 inject.
    # ADR-029 — strength<=0 tombstone 은 skip (decay 로 expired 된 marker).
    if low_level.markers is not None:
        try:
            from low_level.markers import Marker as _Marker
            rows = dmn_artifacts.latest_markers()
            restored_markers = 0
            for r in rows:
                payload = r.get('payload') or {}
                pid = str(payload.get('pattern_id', '')).strip()
                if not pid:
                    continue
                strength = float(payload.get('strength', 0.0))
                if strength <= 0.0:
                    # ADR-029 tombstone — 이미 expired 된 marker, 복원 X.
                    continue
                low_level.markers.markers[pid] = _Marker(
                    pattern_id=pid,
                    valence=float(payload.get('valence', 0.0)),
                    strength=strength,
                    age=int(payload.get('age', 0)),
                )
                restored_markers += 1
            if restored_markers > 0:
                orch._log_event_safe('markers_restored', {
                    'count': restored_markers,
                })
        except Exception:
            pass

    # LLM 콜 단위 latency 도 events.jsonl 에 흘려보낸다. logger 가 set_logger 로
    # 나중에 붙더라도 _log_event_safe 가 None 체크하므로 안전.
    def _llm_event_sink(payload: dict) -> None:
        orch._log_event_safe('llm_call', payload)
    llm_client.event_recorder = _llm_event_sink

    return orch


def main():
    """CLI 진입점.

    환경변수 HUMANOID_MODE:
      'low'      → Phase 1 수동 경험 벡터 모드.
      'dialogue' → Phase 4 대화 루프 (default).
    """
    mode = os.environ.get('HUMANOID_MODE', 'dialogue').lower()
    if mode == 'low':
        return _run_low_level_cli()
    return asyncio.run(_run_dialogue_cli())


async def _run_dialogue_cli():
    """Phase 4 대화 루프 — 사용자 메시지 → process_conversation_turn → 응답."""
    orch = build_full_orchestrator()
    print("=== humanoid v12 — Phase 4: 대화 루프 ===")
    print("'q' = 종료. 빈 줄 = 무입력 턴 (저수준만).")
    print()

    while True:
        try:
            user_input = input(f"[턴 {orch.turn_number + 1}] > ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if user_input.lower() == 'q':
            break
        if not user_input:
            r = orch.run_low_level_only()
            print(
                f"  (저수준만) raw v={r['raw_core_affect']['valence']:.3f} "
                f"a={r['raw_core_affect']['arousal']:.3f}"
            )
            continue

        result = await orch.process_conversation_turn(user_input)
        # 옵션: arousal 기반 sleep — CLI 에서는 비활성. 필요 시 아래 주석 해제.
        # await asyncio.sleep(result['recommended_delay_ms'] / 1000.0)
        print(f"  → {result['response']}")
        print(
            f"     [action={result['action']}, "
            f"delay={result['recommended_delay_ms']}ms, "
            f"mood v={result['low_level']['mood']['valence']:.3f}]"
        )
        print()


def _run_low_level_cli():
    """Phase 1 호환 모드 — 경험 벡터를 수동 주입하며 상태 변화 관찰."""
    orch = build_orchestrator()
    print("=== humanoid v12 — Phase 1: 저수준 파이프라인 ===")
    print(f"안정성 검증: PASS")
    print(f"초기 상태: {orch.low_level.internal_state.to_dict()}")
    print()
    print("경험 벡터를 입력하세요 (reward,novelty,threat,social_reward,goal_progress)")
    print("예: 0.8,0.3,0.0,0.5,0.2  |  빈 줄 = 무입력 턴  |  'q' = 종료")
    print()

    while True:
        try:
            line = input(f"[턴 {orch.turn_number + 1}] > ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if line.lower() == 'q':
            break

        # 경험 벡터 파싱
        if line:
            try:
                values = [float(v) for v in line.split(',')]
                assert len(values) == 5, "5개 값 필요"
                exp = dict(zip(InternalState.EXP_DIMS, values))
            except (ValueError, AssertionError) as e:
                print(f"  파싱 오류: {e}")
                continue
        else:
            exp = {}

        orch.prev_experience = exp
        result = orch.run_low_level_only()

        # 출력
        state = result['state']
        ca = result['raw_core_affect']
        mood = result['mood']
        drives = result['drives']['fulfillment']
        max_def = result['drives']['max_deficit']

        print(f"  상태: { {k: round(v, 3) for k, v in state.items()} }")
        print(f"  코어어펙트: v={ca['valence']:.3f}, a={ca['arousal']:.3f}")
        print(f"  기분: v={mood['valence']:.3f}, a={mood['arousal']:.3f}")
        print(f"  드라이브: { {k: round(v, 3) for k, v in drives.items()} }")
        print(f"  최대결핍: {max_def:.3f}")
        print()


if __name__ == '__main__':
    main()
