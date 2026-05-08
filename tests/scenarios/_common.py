"""시나리오 통합 테스트 공용 헬퍼.

시나리오 파일들이 공유하는 부품:
- ``_build_mocked_orchestrator`` — 모든 LLM 컴포넌트가 ``MockLLMClient`` 로 교체된 풀 오케스트레이터.
- ``_default_response_fn`` — user 메시지 substring 으로 단계별 JSON 응답을 라우팅.
- ``copy_temperament_yaml`` / ``write_temperament_yaml`` — 시나리오마다 baseline 을 살짝 바꾼 기질 파일을 생성.

설계 메모
- ``main.build_full_orchestrator`` 는 `./chroma_db/`, `./storage_data/` 를 cwd 기준으로 생성한다.
  테스트가 cwd 를 오염시키지 않도록 ``test_orchestrator_e2e.py`` 의 직접 조립 패턴을 사용하되
  DMN 까지 포함시킨다. 모든 영속 경로는 ``tmp_path`` 하위로 격리.
- LLMClient 는 절대 생성하지 않는다 → 실 API 호출 0회.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Awaitable, Callable

import yaml

from core.event_bus import EventBus
from core.orchestrator import Orchestrator
from core.trigger_registry import TriggerRegistry
from high_level.candidate_generation import CandidateGeneration
from high_level.dmn import DMN
from high_level.emotion_appraisal import EmotionAppraisal
from high_level.final_judgment import FinalJudgment
from high_level.memory_retrieval import MemoryRetrieval
from high_level.metacognition import Metacognition
from high_level.output_postprocess import OutputPostprocess
from high_level.social_cognition import SocialCognition
from interface.experience_descent import ExperienceDescent
from interface.signal_rise import SignalRise
from llm.mock import MockLLMClient
from main import build_low_level
from storage.memory_store import EpisodicMemory
from storage.other_model import OtherModel
from storage.prospective import ProspectiveQueue
from storage.self_model import SelfModel
from storage.vector_db import VectorDB


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = _PROJECT_ROOT / 'config' / 'temperament_test.yaml'


# ---------------------------------------------------------------------------
# 응답 라우팅 — message substring 으로 단계 식별
# ---------------------------------------------------------------------------


# 시나리오 미세 조정용 — 외부에서 덮어쓸 수 있는 단계별 기본 JSON.
DEFAULT_EMOTION = {
    "valence": 0.0,
    "arousal": 0.3,
    "preliminary_labels": ["중립"],
    "experience_dimensions": {"reward": 0.3, "threat": 0.0, "novelty": 0.2},
}

DEFAULT_CANDIDATES = {
    "candidates": [
        {"style": "emotional", "text": "정말 그랬구나."},
        {"style": "restrained", "text": "그렇게 느꼈군요."},
        {"style": "humor", "text": "그래서 우리는 웃기로 한 거지!"},
        {"style": "silence", "text": "..."},
    ]
}

DEFAULT_FINAL = {
    "selected_index": 1,
    "text": "그렇게 느꼈군요.",
    "rationale": "톤 매칭",
    "marker_match": "none",
}

DEFAULT_TONE = {"response_valence": 0.1, "response_arousal": 0.4, "rationale": "ok"}

DEFAULT_SOCIAL = {
    "person_id": "u",
    "estimated_emotion": {"valence": 0.0, "arousal": 0.3},
    "estimated_intent": "",
    "social_reward": 0.3,
}


def _stage_for(messages: list[dict]) -> str:
    """messages[-1].content 의 단서를 보고 어떤 단계인지 라벨링."""
    if not messages:
        return 'unknown'
    last = messages[-1].get('content', '') if isinstance(messages[-1], dict) else ''
    # 후보 생성 프롬프트 — `n_candidates` 변수 또는 style/emotional/restrained 단어가 포함된다.
    if 'emotional' in last and 'restrained' in last and 'humor' in last:
        return 'candidates'
    # 최종 판단 프롬프트
    if 'selected_index' in last or '최종 판단' in last:
        return 'final'
    # 톤 평가/조정
    if 'response_valence' in last or '톤' in last or 'tone' in last.lower():
        return 'tone'
    # 사회인지 — 규범, social_reward 등 키워드
    if '사회인지' in last or 'social_reward' in last or '규범' in last:
        return 'social'
    # 재평가 (reframe/distance/context 전략 + previous_appraisal 박힘)
    if 'previous_appraisal' in last or '재평가' in last:
        return 'reappraise'
    # 기본은 감정 평가
    return 'emotion'


def make_response_fn(
    *,
    emotion: dict | None = None,
    reappraise: dict | None = None,
    candidates: dict | None = None,
    final: dict | None = None,
    tone: dict | None = None,
    social: dict | None = None,
):
    """단계별 응답을 dict 로 받아 ``response_fn`` 클로저를 만든다.

    각 인자에 ``None`` 을 주면 기본값(`DEFAULT_*`)을 사용한다.
    인자가 ``callable`` 이면 매 호출 시 호출해 동적 응답을 만들 수 있다 (turn 기반 변화).
    """
    table: dict[str, object] = {
        'emotion': emotion if emotion is not None else DEFAULT_EMOTION,
        'reappraise': reappraise if reappraise is not None else DEFAULT_EMOTION,
        'candidates': candidates if candidates is not None else DEFAULT_CANDIDATES,
        'final': final if final is not None else DEFAULT_FINAL,
        'tone': tone if tone is not None else DEFAULT_TONE,
        'social': social if social is not None else DEFAULT_SOCIAL,
    }

    async def _fn(messages, model_name):  # noqa: ARG001 — model_name 은 단계 식별에 부차적
        stage = _stage_for(messages)
        payload = table.get(stage, table['emotion'])
        if callable(payload):
            payload = payload(messages, model_name)
        return json.dumps(payload, ensure_ascii=False)

    return _fn


_default_response_fn = make_response_fn()


# ---------------------------------------------------------------------------
# Orchestrator 조립 — tmp_path 격리 + 모든 LLM = MockLLMClient
# ---------------------------------------------------------------------------


ResponseFn = Callable[[list, str], Awaitable[str]]


def _build_mocked_orchestrator(
    tmp_path: Path,
    response_fn: ResponseFn | None = None,
    *,
    config_path: str | Path | None = None,
    auto_register_triggers: bool = True,
) -> Orchestrator:
    """모든 LLM 컴포넌트가 MockLLMClient 로 교체된 풀 오케스트레이터를 만든다.

    Args:
        tmp_path: 영속 저장소(Chroma, sqlite) 격리 디렉토리.
        response_fn: 미지정 시 ``_default_response_fn`` 사용.
        config_path: 기질 YAML. 미지정 시 ``temperament_test.yaml``.
        auto_register_triggers: 기본 트리거 등록 여부 (Phase 5 호환).
    """
    cfg_path = Path(config_path) if config_path is not None else DEFAULT_CONFIG_PATH
    low_level = build_low_level(cfg_path)
    cfg = low_level.temperament.config

    mock = MockLLMClient(response_fn=response_fn or _default_response_fn)

    chroma_dir = tmp_path / "chroma"
    chroma_dir.mkdir(parents=True, exist_ok=True)
    vdb = VectorDB(
        collection_name="scenarios_test",
        persist_dir=str(chroma_dir),
    )
    episodic = EpisodicMemory(
        vector_db=vdb,
        reconsolidation_alpha=cfg.get('reconsolidation_alpha', 0.3),
    )
    prospective = ProspectiveQueue(db_path=str(tmp_path / "prospective.db"))

    metacog = Metacognition(
        sensitivity=cfg.get('metacognition_sensitivity', 0.5),
        floor=cfg.get('metacognition_floor', 0.1),
        recovery_rate=cfg.get('meta_resource_recovery', 0.05),
        regulation_capacity=cfg.get('emotion_regulation_capacity', 0.5),
    )

    dmn = DMN(base_activity=cfg.get('dmn_base_activity', 0.5))
    dmn.llm = mock

    # 사회인지: SocialCognition 은 자체 LLMClient 를 만들기 때문에 mock 으로 덮어쓴다.
    social_cog = SocialCognition(llm_client=mock)

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
        emotion_appraisal=EmotionAppraisal(llm_client=mock),
        social_cognition=social_cog,
        memory_retrieval=MemoryRetrieval(
            episodic=episodic, prospective=prospective
        ),
        candidate_generation=CandidateGeneration(llm_client=mock),
        final_judgment=FinalJudgment(llm_client=mock),
        output_postprocess=OutputPostprocess(llm_client=mock),
        metacognition=metacog,
        dmn=dmn,
        episodic_memory=episodic,
        self_model=SelfModel(),
        other_model=OtherModel(),
    )
    if auto_register_triggers:
        orch.register_default_triggers()

    # 테스트가 mock 을 직접 다룰 일이 잦아서 attach.
    orch._mock_llm = mock  # type: ignore[attr-defined]
    return orch


# ---------------------------------------------------------------------------
# 기질 YAML 빌더 — 시나리오 별 baseline 변형용
# ---------------------------------------------------------------------------


def copy_temperament_yaml(
    tmp_path: Path,
    *,
    name: str = 'scenario',
    baseline_overrides: dict[str, float] | None = None,
    config_overrides: dict[str, object] | None = None,
) -> Path:
    """temperament_test.yaml 을 복사한 뒤 baselines 만 일부 덮어쓴 새 파일을 만든다.

    반환된 Path 를 ``_build_mocked_orchestrator(config_path=...)`` 로 넘기면 된다.
    """
    src = DEFAULT_CONFIG_PATH
    with src.open('r', encoding='utf-8') as f:
        cfg = yaml.safe_load(f)

    if baseline_overrides:
        cfg.setdefault('baselines', {}).update(baseline_overrides)
    if config_overrides:
        cfg.update(config_overrides)
    # name 은 storage 분리에 쓰이므로 유일하게.
    cfg['name'] = name

    out = tmp_path / f"temperament_{name}.yaml"
    with out.open('w', encoding='utf-8') as f:
        yaml.safe_dump(cfg, f, allow_unicode=True)
    return out
