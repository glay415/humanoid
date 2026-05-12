"""tests/persona_eval/runner.py — 페르소나 회귀 시험지 실행기.

흐름:
  1. backend (uvicorn, http://127.0.0.1:8000) health check.
  2. scenarios/*.yaml 모두 로드.
  3. 각 시나리오 × applies_to_personas 의 페르소나마다:
       a. 새 인스턴스 spawn (API). 이 spawn 의 jitter_seed 는 API 가
          random 이므로 본 runner 가 강제하진 않음 — 결과 로그에 seed 를 기록해
          재현 가능. 또는 환경변수 PERSONA_EVAL_INSTANCE_PREFIX 로
          pre-spawned instance_id 를 골라 hard-reset 후 사용 가능.
       b. scenario.turns 의 user_input 들 순차 호출 (SSE).
       c. judge.py 가 응답을 expected/forbidden signals 로 채점.
       d. PASS / FAIL + 이유 출력.
       e. 임시 spawn 인스턴스는 끝나면 delete (admin token 있을 때).
  4. 마지막 요약 (X PASS / Y FAIL).
  5. exit code: 0 = 모두 PASS, 1 = 하나라도 FAIL, 2 = 인프라 오류.

backend 가 안 떠있으면 명확한 메시지 + exit code 2.

CLI:
  uv run python tests/persona_eval/runner.py [--scenario <id>] [--persona <mbti>]
                                              [--verbose] [--base-url <url>]
                                              [--keep-instances]

LLM 비용 주의 — 실제 OpenAI 콜이 발생한다. 일반 pytest 에 포함되지 않음.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import yaml


# `python tests/persona_eval/runner.py` 직접 실행 시 repo root 가 sys.path 에
# 없어 `from tests.persona_eval.judge import Judge` 가 실패한다. repo root 를
# 명시적으로 추가해서 두 호출 방식 모두 호환 (uv run python -m 도 OK).
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))



sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')


REPO_ROOT = Path(__file__).resolve().parents[2]
SCENARIO_DIR = Path(__file__).resolve().parent / 'scenarios'
PERSONAS_DIR = REPO_ROOT / 'config' / 'personas'

DEFAULT_BASE = 'http://127.0.0.1:8000'
RATE_LIMIT_SLEEP_S = 7.0  # backend /turn 10/min 제한 우회


@dataclass
class ScenarioRun:
    scenario_id: str
    persona_id: str
    instance_id: str
    jitter_seed: int | None
    turns: list[dict] = field(default_factory=list)  # {user_input, response}
    judgment: Any = None  # judge.Judgment
    error: str | None = None

    @property
    def passed(self) -> bool:
        if self.error or self.judgment is None:
            return False
        return self.judgment.all_passed


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_scenarios(scenario_filter: str | None = None) -> list[dict]:
    if not SCENARIO_DIR.exists():
        raise FileNotFoundError(f"scenarios dir missing: {SCENARIO_DIR}")
    files = sorted(SCENARIO_DIR.glob('*.yaml'))
    if not files:
        raise FileNotFoundError(f"no scenarios in {SCENARIO_DIR}")
    # comma 구분 다중 시나리오 id 도 허용.
    wanted_ids: set[str] | None = None
    if scenario_filter:
        wanted_ids = {s.strip() for s in scenario_filter.split(',') if s.strip()}
    out: list[dict] = []
    for f in files:
        with f.open('r', encoding='utf-8') as fp:
            data = yaml.safe_load(fp) or {}
        if 'id' not in data:
            print(f"[WARN] {f.name}: missing 'id' — skipped", flush=True)
            continue
        if wanted_ids is not None and data['id'] not in wanted_ids:
            continue
        data['_source_file'] = f.name
        out.append(data)
    if wanted_ids is not None and not out:
        raise ValueError(f"scenario id {sorted(wanted_ids)!r} not found")
    return out


def list_available_personas() -> list[str]:
    if not PERSONAS_DIR.exists():
        return []
    return sorted(p.stem for p in PERSONAS_DIR.glob('*.yaml'))


def narrative_excerpt(persona_id: str, max_chars: int = 1500) -> str:
    fpath = PERSONAS_DIR / f"{persona_id}.yaml"
    if not fpath.exists():
        return ''
    try:
        with fpath.open('r', encoding='utf-8') as f:
            data = yaml.safe_load(f) or {}
    except Exception:
        return ''
    seed = (data.get('narrative_seed') or '').strip()
    if len(seed) > max_chars:
        return seed[:max_chars] + '\n…(truncated)'
    return seed


async def fetch_instance_narrative(
    client: httpx.AsyncClient,
    base: str,
    instance_id: str,
    max_chars: int = 2500,
) -> str:
    """spawn 후 backend 에서 실제 합성된 narrative 를 가져온다.

    sample_life (ADR-013 Stage 2) 가 persona narrative_seed 위에 무작위로 추가한
    interests/knowledge 가 self_model.narrative 안에 포함됨. judge 가 채점할 때
    이 *런타임 narrative* 를 봐야 instance 가 sample_life 로 받은 관심사로 답한
    걸 "narrative 와 결 맞는 답" 으로 인정한다 (interest_match 시나리오 등).
    """
    try:
        r = await client.get(f"{base}/api/instances/{instance_id}", timeout=10.0)
        if r.status_code != 200:
            return ''
        payload = r.json()
    except Exception:
        return ''
    narrative = (
        ((payload.get('self_model') or {}).get('narrative')) or ''
    ).strip()
    if not narrative:
        return ''
    if len(narrative) > max_chars:
        return narrative[:max_chars] + '\n…(truncated)'
    return narrative


# ---------------------------------------------------------------------------
# Backend interaction
# ---------------------------------------------------------------------------


async def health_check(client: httpx.AsyncClient, base: str) -> None:
    try:
        r = await client.get(f"{base}/api/health", timeout=5.0)
    except Exception as exc:
        raise RuntimeError(
            f"backend health check failed at {base}/api/health — backend 가 떠있어야 한다. "
            f"`uv run uvicorn ui.backend.app:app --port 8000` 로 띄우세요. "
            f"(error: {exc!r})"
        )
    if r.status_code != 200:
        raise RuntimeError(
            f"backend /api/health → HTTP {r.status_code}: {r.text!r}"
        )


async def spawn_instance(client: httpx.AsyncClient, base: str, persona_id: str) -> dict:
    r = await client.post(
        f"{base}/api/instances",
        json={'persona_id': persona_id, 'display_name': f'eval_{persona_id}',
              'jitter': 0.0},  # eval 은 jitter 0 — 페르소나 원형 그대로.
        timeout=30.0,
    )
    if r.status_code != 201:
        raise RuntimeError(
            f"spawn failed for persona={persona_id}: HTTP {r.status_code} {r.text!r}"
        )
    return r.json()


async def delete_instance(client: httpx.AsyncClient, base: str, instance_id: str,
                          admin_token: str | None) -> None:
    headers = {}
    if admin_token:
        headers['x-admin-token'] = admin_token
    try:
        await client.delete(
            f"{base}/api/instances/{instance_id}",
            headers=headers,
            timeout=10.0,
        )
    except Exception as exc:
        print(f"[WARN] delete instance {instance_id} 실패 (무시): {exc!r}", flush=True)


async def apply_preconditions(
    client: httpx.AsyncClient,
    base: str,
    instance_id: str,
    preconditions: dict,
) -> None:
    """시나리오 yaml 의 preconditions 섹션을 backend 에 적용.

    현재 지원:
      - metacog_resource: float — POST /api/instances/{id}/debug/metacog.
        spawn 직후 metacognition.resource 가 1.0 인데, 자원 낮은 상태의 emergent
        행동을 검증하려면 강제로 낮춰야 한다. 0.0 ~ 1.0 범위 밖이면 backend 가 400.

    실패 시 RuntimeError. 시나리오에 preconditions 가 없거나 빈 dict 면 no-op.
    """
    if not preconditions:
        return
    if 'metacog_resource' in preconditions:
        resource = float(preconditions['metacog_resource'])
        r = await client.post(
            f"{base}/api/instances/{instance_id}/debug/metacog",
            json={'resource': resource},
            timeout=10.0,
        )
        if r.status_code != 200:
            raise RuntimeError(
                f"precondition metacog_resource={resource} failed: "
                f"HTTP {r.status_code} {r.text!r}"
            )


async def post_turn(
    client: httpx.AsyncClient,
    base: str,
    instance_id: str,
    user_input: str,
) -> str:
    """한 turn 호출 + SSE 파싱해서 done 의 response 텍스트 반환."""
    response_parts: list[str] = []
    full_response = ''
    event_name: str | None = None
    async with client.stream(
        'POST', f"{base}/api/instances/{instance_id}/turn",
        json={'user_input': user_input}, timeout=120.0,
    ) as resp:
        if resp.status_code != 200:
            body = await resp.aread()
            raise RuntimeError(
                f"turn HTTP {resp.status_code}: {body[:200]!r}"
            )
        async for raw in resp.aiter_lines():
            if not raw:
                continue
            if raw.startswith('event:'):
                event_name = raw[len('event:'):].strip()
            elif raw.startswith('data:'):
                data = raw[len('data:'):].lstrip()
                try:
                    parsed = json.loads(data)
                except Exception:
                    continue
                if event_name == 'response_chunk':
                    response_parts.append(parsed.get('text', ''))
                elif event_name == 'done':
                    full_response = parsed.get('response', '')
    return full_response or ''.join(response_parts)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def resolve_personas(scenario: dict, all_personas: list[str],
                     persona_filter: str | None) -> list[str]:
    raw = scenario.get('applies_to_personas')
    if raw is None:
        candidates = list(all_personas)
    else:
        candidates = [p for p in raw if p in all_personas]
        missing = [p for p in raw if p not in all_personas]
        for m in missing:
            print(f"[WARN] scenario {scenario['id']}: persona {m!r} not in "
                  f"config/personas — skipped", flush=True)
    if persona_filter:
        # comma 구분 다중 페르소나 필터도 허용 (예: --persona infp,intj,estp).
        wanted = {p.strip() for p in persona_filter.split(',') if p.strip()}
        candidates = [p for p in candidates if p in wanted]
    return candidates


async def run_scenario(
    *,
    client: httpx.AsyncClient,
    base: str,
    scenario: dict,
    persona_id: str,
    judge,
    verbose: bool,
    keep_instances: bool,
    admin_token: str | None,
) -> ScenarioRun:
    run = ScenarioRun(
        scenario_id=scenario['id'],
        persona_id=persona_id,
        instance_id='',
        jitter_seed=None,
    )
    instance_id = ''
    try:
        spawn_card = await spawn_instance(client, base, persona_id)
        instance_id = spawn_card['instance_id']
        run.instance_id = instance_id
        # spawn 응답에 jitter_seed 가 노출 안 되더라도 instance state 에 보존됨.
        # 로그에 남기고 싶으면 GET /api/instances/{id} 로 fetch. (선택)

        # 시나리오에 preconditions 가 있으면 turn 호출 전에 적용. 예) metacog_resource
        # 를 0.15 로 강제해 자원 낮은 상태의 emergent 행동 검증.
        await apply_preconditions(
            client, base, instance_id, scenario.get('preconditions') or {},
        )

        for turn_idx, turn in enumerate(scenario.get('turns', [])):
            user_input = turn['user_input']
            if turn_idx > 0:
                # backend /turn rate limit (10/min) 우회.
                await asyncio.sleep(RATE_LIMIT_SLEEP_S)
            t0 = time.perf_counter()
            response = await post_turn(client, base, instance_id, user_input)
            dt_ms = (time.perf_counter() - t0) * 1000
            run.turns.append({
                'user_input': user_input,
                'response': response,
            })
            if verbose:
                print(f"    [{persona_id}] turn {turn_idx+1} ({dt_ms:.0f}ms)\n"
                      f"      user> {user_input}\n"
                      f"      asst> {response[:200]}{'…' if len(response) > 200 else ''}",
                      flush=True)

        # 채점 — base narrative_seed + 런타임 합성 narrative 둘 다 본다.
        # 런타임 narrative 는 sample_life 가 추가한 interests/knowledge 가 들어
        # 있으므로 ('아침 카페' 외에 spawn 시 무작위로 받은 '클라이밍' 등),
        # judge 가 이 풍부한 컨텍스트로 채점하지 않으면 "narrative 와 결 안 맞음"
        # 으로 오판한다 (ADR-013 Stage 2 grounding).
        base_excerpt = narrative_excerpt(persona_id)
        runtime_excerpt = await fetch_instance_narrative(client, base, instance_id)
        if runtime_excerpt:
            excerpt = (
                f"## base narrative_seed (페르소나 yaml)\n{base_excerpt}\n\n"
                f"## runtime narrative (sample_life 적용 — 이 instance 의 실제 결)\n"
                f"{runtime_excerpt}"
            )
        else:
            excerpt = base_excerpt
        run.judgment = await judge.judge(
            scenario=scenario,
            persona_id=persona_id,
            narrative_excerpt=excerpt,
            turn_responses=run.turns,
        )
    except Exception as exc:
        run.error = repr(exc)
    finally:
        if instance_id and not keep_instances:
            await delete_instance(client, base, instance_id, admin_token)
    return run


def print_run_result(run: ScenarioRun, verbose: bool) -> None:
    status = 'PASS' if run.passed else 'FAIL'
    print(f"  [{status}] scenario={run.scenario_id} persona={run.persona_id}",
          flush=True)
    if run.error:
        print(f"    ! ERROR: {run.error}", flush=True)
        return
    if run.judgment is None:
        print(f"    ! no judgment", flush=True)
        return
    for sig in run.judgment.signals:
        mark = 'ok' if sig.passed else 'X'
        if sig.passed and not verbose:
            continue
        print(f"    [{mark}] ({sig.kind}) {sig.id}: {sig.reason}", flush=True)


async def amain(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--scenario', help='scenario id (기본: 모두). comma 구분 다중 가능 (예: meta_identity,mood_state_reflection).')
    parser.add_argument('--persona', help='persona id 필터 (기본: scenario 의 applies_to_personas). comma 구분 다중 가능 (예: infp,intj,estp).')
    parser.add_argument('--verbose', action='store_true',
                        help='passing signal 의 reason 까지 출력 + turn 별 응답')
    parser.add_argument('--base-url', default=os.environ.get('PERSONA_EVAL_BASE_URL', DEFAULT_BASE),
                        help=f'backend base URL (default: {DEFAULT_BASE})')
    parser.add_argument('--keep-instances', action='store_true',
                        help='실행 후 spawn 한 인스턴스 삭제하지 않음')
    args = parser.parse_args(argv)

    admin_token = os.environ.get('HUMANOID_ADMIN_TOKEN')

    # judge 는 LLMClient 를 쓰므로 backend 와 별개로 LLM 키 필요.
    from tests.persona_eval.judge import Judge  # local import — heavy deps lazy
    judge = Judge()

    try:
        scenarios = load_scenarios(args.scenario)
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr, flush=True)
        return 2

    available = list_available_personas()
    if not available:
        print(f"ERROR: no personas found under {PERSONAS_DIR}", file=sys.stderr, flush=True)
        return 2

    print(f"== persona_eval ==", flush=True)
    print(f"   base: {args.base_url}", flush=True)
    print(f"   scenarios: {len(scenarios)} ({', '.join(s['id'] for s in scenarios)})", flush=True)

    async with httpx.AsyncClient() as client:
        try:
            await health_check(client, args.base_url)
        except RuntimeError as exc:
            print(f"ERROR: {exc}", file=sys.stderr, flush=True)
            return 2

        results: list[ScenarioRun] = []
        for sc in scenarios:
            personas = resolve_personas(sc, available, args.persona)
            if not personas:
                print(f"\n-- scenario {sc['id']}: 적용 페르소나 없음 (skip)", flush=True)
                continue
            print(f"\n-- scenario {sc['id']}: {len(personas)} persona(s)", flush=True)
            for pid in personas:
                run = await run_scenario(
                    client=client,
                    base=args.base_url,
                    scenario=sc,
                    persona_id=pid,
                    judge=judge,
                    verbose=args.verbose,
                    keep_instances=args.keep_instances,
                    admin_token=admin_token,
                )
                results.append(run)
                print_run_result(run, args.verbose)
                # rate-limit 우회 (다음 spawn/turn 전에 잠깐 쉰다).
                await asyncio.sleep(RATE_LIMIT_SLEEP_S / 2)

    # 요약
    passed = sum(1 for r in results if r.passed)
    failed = len(results) - passed
    print(f"\n== summary: {passed} PASS / {failed} FAIL (of {len(results)}) ==", flush=True)
    if failed:
        print("FAIL detail:", flush=True)
        for r in results:
            if r.passed:
                continue
            print(f"  - scenario={r.scenario_id} persona={r.persona_id} "
                  f"instance={r.instance_id} error={r.error or 'signals'}", flush=True)
    return 0 if failed == 0 else 1


def main() -> int:
    return asyncio.run(amain())


if __name__ == '__main__':
    sys.exit(main())
