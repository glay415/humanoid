"""ui.backend FastAPI 통합 테스트.

규칙:
- 절대 실제 OpenAI 호출 금지 → MockLLMClient 만 사용.
- TestClient (sync, 별도 스레드) 는 storage/prospective.py 의 sqlite 단일 스레드 제약과
  충돌 → httpx.AsyncClient + ASGITransport 로 동일 이벤트 루프에서 호출.
- /api/turn 은 SSE 라 stream 으로 받아서 raw 바디를 \\n\\n 단위로 split 해 파싱.
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
# 정형 LLM 응답 페이로드 (test_orchestrator_e2e.py 와 동일 패턴)
# ---------------------------------------------------------------------------


def _emotion_payload(valence: float = 0.3, arousal: float = 0.5) -> str:
    return json.dumps({
        "valence": valence,
        "arousal": arousal,
        "preliminary_labels": ["기쁨"],
        "experience_dimensions": {
            "reward": max(0.0, valence),
            "threat": max(0.0, -valence),
            "novelty": 0.2,
        },
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


def _final_payload(text: str = "괜찮은 결과네.") -> str:
    return json.dumps({
        "selected_index": 1,
        "text": text,
        "rationale": "ok",
        "marker_match": "approach",
    })


def _tone_payload(response_valence: float = 0.3) -> str:
    return json.dumps({
        "response_valence": response_valence,
        "response_arousal": 0.4,
        "rationale": "ok",
    })


def _full_turn_responses() -> list[str]:
    """한 턴이 LLMError 없이 끝까지 가도록 4개 응답 묶음."""
    return [
        _emotion_payload(),
        _candidates_payload(),
        _final_payload(),
        _tone_payload(),
    ]


# ---------------------------------------------------------------------------
# 헬퍼: STATE 를 Mock 으로 갈아끼우기
# ---------------------------------------------------------------------------


def _build_mocked_orchestrator(tmp_path: Path, mock: MockLLMClient) -> Orchestrator:
    """test_orchestrator_e2e._build_orchestrator_with_mock 와 동일 패턴."""
    low_level = build_low_level(CONFIG_PATH)
    cfg = low_level.temperament.config

    vdb = VectorDB(
        collection_name="ui_backend_test",
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
    """STATE.orchestrator 를 mock 으로 갈아끼우고 yield. 끝나면 STATE 비운다."""
    mock = MockLLMClient()
    orch = _build_mocked_orchestrator(tmp_path, mock)
    STATE.orchestrator = orch
    STATE.mood_history = []
    yield app, mock
    # cleanup — 다른 테스트가 STATE 잔재 안 보이게.
    STATE.orchestrator = None
    STATE.mood_history = []


def _async_client(asgi_app) -> AsyncClient:
    """ASGI transport 로 in-process httpx 클라이언트. lifespan 은 발동 안 됨."""
    transport = ASGITransport(app=asgi_app)
    return AsyncClient(transport=transport, base_url="http://test")


# ---------------------------------------------------------------------------
# SSE 파서 — 빈 줄(\n\n) 기준으로 분리하고 'event:' / 'data:' 라인 추출
# ---------------------------------------------------------------------------


def _parse_sse(body: str) -> list[dict]:
    """SSE 바디 → [{event, data_json_str}, ...]. data 가 여러 줄일 가능성도 처리."""
    events: list[dict] = []
    # 메시지 사이는 빈 줄 — \r\n\r\n 또는 \n\n 둘 다 허용.
    chunks = body.replace('\r\n', '\n').split('\n\n')
    for chunk in chunks:
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
            # event 가 없는 메시지(comment/keepalive) 는 건너뜀.
            continue
        events.append({'event': ev_name, 'data': '\n'.join(data_lines)})
    return events


async def _post_turn_collect(asgi_app, user_input: str) -> list[dict]:
    """POST /api/turn → SSE 바디 전체를 모은 뒤 파싱한 이벤트 리스트 반환."""
    async with _async_client(asgi_app) as client:
        async with client.stream(
            'POST', '/api/turn', json={'user_input': user_input}
        ) as resp:
            assert resp.status_code == 200, resp.status_code
            chunks: list[bytes] = []
            async for chunk in resp.aiter_bytes():
                chunks.append(chunk)
    body = b''.join(chunks).decode('utf-8')
    return _parse_sse(body)


# ---------------------------------------------------------------------------
# 1. /api/health
# ---------------------------------------------------------------------------


async def test_health_returns_ok(mocked_app):
    app_, _mock = mocked_app
    async with _async_client(app_) as client:
        r = await client.get('/api/health')
    assert r.status_code == 200
    body = r.json()
    assert body['ok'] is True
    assert body['turn_number'] == 0


# ---------------------------------------------------------------------------
# 2. /api/state — fresh
# ---------------------------------------------------------------------------


async def test_state_initial_has_zero_turns(mocked_app):
    app_, _mock = mocked_app
    async with _async_client(app_) as client:
        r = await client.get('/api/state')
    assert r.status_code == 200
    body = r.json()
    assert body['turn_number'] == 0
    assert body['mood_history'] == []
    # internal_state 9 keys
    assert len(body['internal_state']) == 9
    assert set(body['internal_state'].keys()) == {
        'reward', 'patience', 'arousal', 'learning',
        'excitation', 'inhibition', 'stress', 'bonding', 'comfort',
    }
    # baselines 도 9개
    assert len(body['baselines']) == 9
    # 기타 키
    assert 'drives' in body
    assert 'raw_core_affect' in body
    assert 'markers' in body
    assert 'self_model' in body
    assert 'meta_resource' in body


# ---------------------------------------------------------------------------
# 3. /api/turn — full SSE 시퀀스
# ---------------------------------------------------------------------------


async def test_turn_emits_full_sse_sequence(mocked_app):
    app_, mock = mocked_app
    mock.responses = _full_turn_responses()
    events = await _post_turn_collect(app_, "오늘 발표 잘 끝났어")
    names = [e['event'] for e in events]
    expected = ['low_level', 'emotion', 'memory', 'candidates', 'final', 'tone', 'done']
    # error 가 끼어들면 안 됨 (정상 경로)
    assert 'error' not in names, f"unexpected error event in {names}"
    assert names == expected, f"got {names}"
    # done 이벤트 페이로드 검증
    done = json.loads(events[-1]['data'])
    assert isinstance(done['response'], str) and done['response']
    assert done['turn_number'] == 1
    assert 'experience_vector' in done


# ---------------------------------------------------------------------------
# 4. turn_number 증가
# ---------------------------------------------------------------------------


async def test_turn_increments_turn_number(mocked_app):
    app_, mock = mocked_app
    mock.responses = _full_turn_responses()
    await _post_turn_collect(app_, "안녕")
    async with _async_client(app_) as client:
        r = await client.get('/api/state')
    assert r.status_code == 200
    assert r.json()['turn_number'] == 1


# ---------------------------------------------------------------------------
# 5. mood_history 누적
# ---------------------------------------------------------------------------


async def test_two_turns_appended_to_mood_history(mocked_app):
    app_, mock = mocked_app
    mock.responses = _full_turn_responses() + _full_turn_responses()
    await _post_turn_collect(app_, "첫째 입력")
    await _post_turn_collect(app_, "둘째 입력")
    async with _async_client(app_) as client:
        r = await client.get('/api/state')
    body = r.json()
    assert body['turn_number'] == 2
    assert len(body['mood_history']) == 2
    assert body['mood_history'][0]['turn'] == 1
    assert body['mood_history'][1]['turn'] == 2
    for entry in body['mood_history']:
        assert 'valence' in entry and 'arousal' in entry


# ---------------------------------------------------------------------------
# 6. /api/reset — turn 후 호출하면 turn_number/mood_history 초기화
# ---------------------------------------------------------------------------


async def test_reset_clears_state(mocked_app, monkeypatch, tmp_path):
    app_, mock = mocked_app
    mock.responses = _full_turn_responses()
    await _post_turn_collect(app_, "한 번")

    # POST /api/reset 가 build_full_orchestrator 를 호출하므로 — 실제 LLMClient init
    # 을 막기 위해 STATE.initialize 를 fixture 기반 mock 빌더로 모킹.
    rebuilt_mock = MockLLMClient()
    rebuilt = _build_mocked_orchestrator(tmp_path / "after_reset", rebuilt_mock)

    def fake_initialize(self, config_path=None):
        self.orchestrator = rebuilt
        self.mood_history.clear()

    monkeypatch.setattr(
        type(STATE), 'initialize', fake_initialize, raising=True
    )

    async with _async_client(app_) as client:
        r = await client.post('/api/reset')
    assert r.status_code == 204

    async with _async_client(app_) as client:
        r2 = await client.get('/api/state')
    body = r2.json()
    assert body['turn_number'] == 0
    assert body['mood_history'] == []


# ---------------------------------------------------------------------------
# 7. emotion 단계 LLMError 시 error 이벤트 + done 까지 도달
# ---------------------------------------------------------------------------


async def test_turn_emits_error_event_on_emotion_llm_failure_but_still_completes(
    mocked_app,
):
    app_, mock = mocked_app
    # 첫 응답을 invalid JSON 으로 → EmotionAppraisal 이 LLMError raise.
    # streaming.py 가 fallback 으로 _emotion_fallback 사용 + error 이벤트 emit.
    mock.responses = [
        "this is not valid json",
        _candidates_payload(),
        _final_payload(),
        _tone_payload(),
    ]
    events = await _post_turn_collect(app_, "흠...")
    names = [e['event'] for e in events]

    # error 이벤트가 emotion stage 에서 한 번 발생해야 한다.
    error_events = [e for e in events if e['event'] == 'error']
    assert error_events, f"expected at least one error event in {names}"
    assert json.loads(error_events[0]['data'])['stage'] == 'emotion'

    # 그래도 done 까지 도달
    assert names[-1] == 'done', f"expected done last, got {names}"
    done = json.loads(events[-1]['data'])
    assert done['response']
    assert done['turn_number'] == 1


# ---------------------------------------------------------------------------
# 8. CORS 헤더
# ---------------------------------------------------------------------------


async def test_cors_headers_for_vite_dev_origin(mocked_app):
    app_, _mock = mocked_app
    async with _async_client(app_) as client:
        r = await client.options(
            '/api/turn',
            headers={
                'Origin': 'http://localhost:5173',
                'Access-Control-Request-Method': 'POST',
                'Access-Control-Request-Headers': 'content-type',
            },
        )
    # CORSMiddleware 가 200/204 로 preflight 응답해야 한다.
    assert r.status_code in (200, 204)
    allow_origin = r.headers.get('access-control-allow-origin')
    assert allow_origin == 'http://localhost:5173', (
        f"got allow-origin={allow_origin!r}, headers={dict(r.headers)}"
    )
