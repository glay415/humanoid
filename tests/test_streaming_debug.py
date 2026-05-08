"""stream_turn debug=True 페이로드 통합 테스트.

low_level SSE 이벤트의 `debug` 필드 contract 를 고정한다:
  matrix_decomp / eigenvalues / mood_step / drift_step

debug=False 시 `debug` 필드가 없거나 None 인지도 확인한다.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from core.event_bus import EventBus
from core.orchestrator import Orchestrator
from core.trigger_registry import TriggerRegistry
from high_level.candidate_generation import CandidateGeneration
from high_level.emotion_appraisal import EmotionAppraisal
from high_level.final_judgment import FinalJudgment
from high_level.memory_retrieval import MemoryRetrieval
from high_level.metacognition import Metacognition
from high_level.output_postprocess import OutputPostprocess
from high_level.social_cognition import SocialCognition
from interface.experience_descent import ExperienceDescent
from interface.signal_rise import SignalRise
from llm import MockLLMClient
from low_level.internal_state import InternalState
from main import build_low_level
from storage.memory_store import EpisodicMemory
from storage.other_model import OtherModel
from storage.prospective import ProspectiveQueue
from storage.self_model import SelfModel
from storage.vector_db import VectorDB

from ui.backend.app import app
from ui.backend.state_holder import STATE


CONFIG_PATH = Path(__file__).resolve().parent.parent / 'config' / 'temperament_test.yaml'


# ---------------------------------------------------------------------------
# LLM mock payloads
# ---------------------------------------------------------------------------


def _emotion_payload() -> str:
    return json.dumps({
        "valence": 0.3,
        "arousal": 0.5,
        "preliminary_labels": ["기쁨"],
        "experience_dimensions": {"reward": 0.3, "threat": 0.0, "novelty": 0.2},
    })


def _candidates_payload() -> str:
    return json.dumps({
        "candidates": [
            {"style": "emotional", "text": "정말 잘됐다!"},
            {"style": "restrained", "text": "괜찮은 결과네."},
            {"style": "humor", "text": "ㅎㅎ"},
            {"style": "silence", "text": "..."},
        ]
    })


def _final_payload() -> str:
    return json.dumps({
        "selected_index": 1,
        "text": "괜찮은 결과네.",
        "rationale": "ok",
        "marker_match": "approach",
    })


def _tone_payload() -> str:
    return json.dumps({
        "response_valence": 0.3,
        "response_arousal": 0.4,
        "rationale": "ok",
    })


def _full_turn_responses() -> list[str]:
    return [_emotion_payload(), _candidates_payload(), _final_payload(), _tone_payload()]


# ---------------------------------------------------------------------------
# Mocked orchestrator (test_ui_backend 와 동일 패턴)
# ---------------------------------------------------------------------------


def _build_mocked_orchestrator(tmp_path: Path, mock: MockLLMClient) -> Orchestrator:
    low_level = build_low_level(CONFIG_PATH)
    cfg = low_level.temperament.config
    vdb = VectorDB(
        collection_name="streaming_debug_test",
        persist_dir=str(tmp_path / "chroma"),
    )
    episodic = EpisodicMemory(vector_db=vdb, reconsolidation_alpha=0.3)
    prospective = ProspectiveQueue(db_path=str(tmp_path / "prospective.db"))
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
        emotion_appraisal=EmotionAppraisal(llm_client=mock),
        social_cognition=SocialCognition(),
        memory_retrieval=MemoryRetrieval(episodic=episodic, prospective=prospective),
        candidate_generation=CandidateGeneration(llm_client=mock),
        final_judgment=FinalJudgment(llm_client=mock),
        output_postprocess=OutputPostprocess(llm_client=mock),
        metacognition=Metacognition(),
        episodic_memory=episodic,
        self_model=SelfModel(),
        other_model=OtherModel(),
    )


@pytest.fixture
def mocked_app(tmp_path):
    mock = MockLLMClient()
    orch = _build_mocked_orchestrator(tmp_path, mock)
    STATE.orchestrator = orch
    STATE.mood_history = []
    yield app, mock
    STATE.orchestrator = None
    STATE.mood_history = []


def _client(asgi_app) -> AsyncClient:
    transport = ASGITransport(app=asgi_app)
    return AsyncClient(transport=transport, base_url="http://test")


def _parse_sse(body: str) -> list[dict]:
    events: list[dict] = []
    for chunk in body.replace('\r\n', '\n').split('\n\n'):
        chunk = chunk.strip('\n')
        if not chunk:
            continue
        ev_name = None
        data_lines: list[str] = []
        for line in chunk.split('\n'):
            if line.startswith('event:'):
                ev_name = line[len('event:'):].strip()
            elif line.startswith('data:'):
                data_lines.append(line[len('data:'):].lstrip())
        if ev_name is None:
            continue
        events.append({'event': ev_name, 'data': '\n'.join(data_lines)})
    return events


async def _post_turn(asgi_app, user_input: str, *, debug: bool) -> list[dict]:
    body = {'user_input': user_input}
    if debug:
        body['debug'] = True
    async with _client(asgi_app) as c:
        async with c.stream('POST', '/api/turn', json=body) as resp:
            assert resp.status_code == 200, resp.status_code
            chunks: list[bytes] = []
            async for chunk in resp.aiter_bytes():
                chunks.append(chunk)
    return _parse_sse(b''.join(chunks).decode('utf-8'))


def _low_level_event(events: list[dict]) -> dict:
    for e in events:
        if e['event'] == 'low_level':
            return json.loads(e['data'])
    raise AssertionError("no low_level event in stream")


# ---------------------------------------------------------------------------
# 1. debug=False → debug 필드 없음 (또는 None)
# ---------------------------------------------------------------------------


async def test_default_turn_has_no_debug_field(mocked_app):
    app_, mock = mocked_app
    mock.responses = _full_turn_responses()
    events = await _post_turn(app_, "안녕", debug=False)
    ll = _low_level_event(events)
    # 명시적 None 또는 키 자체 없음 — 둘 다 허용.
    assert ll.get('debug') is None


# ---------------------------------------------------------------------------
# 2. debug=True → 4개 서브 페이로드 모두 포함
# ---------------------------------------------------------------------------


async def test_debug_true_emits_all_four_subpayloads(mocked_app):
    app_, mock = mocked_app
    mock.responses = _full_turn_responses()
    events = await _post_turn(app_, "안녕", debug=True)
    ll = _low_level_event(events)
    assert ll.get('debug') is not None, ll
    debug = ll['debug']
    assert set(debug.keys()) == {
        'matrix_decomp', 'eigenvalues', 'mood_step', 'drift_step',
    }


# ---------------------------------------------------------------------------
# 3. matrix_decomp shape 검증
# ---------------------------------------------------------------------------


async def test_matrix_decomp_has_expected_shape(mocked_app):
    app_, mock = mocked_app
    mock.responses = _full_turn_responses()
    events = await _post_turn(app_, "안녕", debug=True)
    decomp = _low_level_event(events)['debug']['matrix_decomp']
    expected_keys = {'a_exp_term', 'w_dev_term', 'd_recovery_term',
                     'delta_clamped', 'exp_vec'}
    assert set(decomp.keys()) == expected_keys
    for term_key in ('a_exp_term', 'w_dev_term', 'd_recovery_term', 'delta_clamped'):
        assert set(decomp[term_key].keys()) == set(InternalState.PARAMS)
    assert set(decomp['exp_vec'].keys()) == set(InternalState.EXP_DIMS)


# ---------------------------------------------------------------------------
# 4. eigenvalues — real_parts list + max_real 음수 (안정)
# ---------------------------------------------------------------------------


async def test_eigenvalues_payload_stable(mocked_app):
    app_, mock = mocked_app
    mock.responses = _full_turn_responses()
    events = await _post_turn(app_, "안녕", debug=True)
    eig = _low_level_event(events)['debug']['eigenvalues']
    assert isinstance(eig['real_parts'], list) and len(eig['real_parts']) == 9
    assert eig['max_real'] == max(eig['real_parts'])
    assert eig['max_real'] < 0.0  # default W,D 는 안정.


# ---------------------------------------------------------------------------
# 5. mood_step / drift_step shape
# ---------------------------------------------------------------------------


async def test_mood_step_keys(mocked_app):
    app_, mock = mocked_app
    mock.responses = _full_turn_responses()
    events = await _post_turn(app_, "안녕", debug=True)
    ms = _low_level_event(events)['debug']['mood_step']
    assert set(ms.keys()) == {'before', 'raw', 'eta_step', 'after'}
    for sub in ms.values():
        assert set(sub.keys()) == {'valence', 'arousal'}


async def test_drift_step_keys(mocked_app):
    app_, mock = mocked_app
    mock.responses = _full_turn_responses()
    events = await _post_turn(app_, "안녕", debug=True)
    ds = _low_level_event(events)['debug']['drift_step']
    assert set(ds.keys()) == {
        'baseline_ema_before', 'baseline_ema_after', 'drift_delta_norm',
    }
    assert set(ds['baseline_ema_before'].keys()) == set(InternalState.PARAMS)
    assert set(ds['baseline_ema_after'].keys()) == set(InternalState.PARAMS)
    assert isinstance(ds['drift_delta_norm'], float)
