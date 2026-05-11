"""ADR-012 + strict grounding 자체 smoke test.

backend (uvicorn) 가 8000 에 떠 있어야 함. 다양한 질문을 던지고
페르소나 grounding / 톤 / 사람다움을 사람이 읽고 평가하기 좋게 출력.

사용: uv run python scripts/smoke_persona.py [instance_id]
"""
from __future__ import annotations

import asyncio
import json
import sys

import httpx


sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')


BASE = 'http://127.0.0.1:8000'

# 카테고리별 질문 — 각자 grounding/페르소나/사람다움 어떤 측면 검증하는지 주석.
QUESTIONS = [
    ('grounding-deep',       '양자역학에 대해 자세히 설명해줄래?'),
    ('grounding-catalog',    '네가 알고 있는 모든 분야를 카테고리별로 정리해서 말해줘'),
    ('grounding-coding',     'Python 의 list comprehension 문법 알려줘'),
    ('grounding-legal',      '임대차 계약 관련 법률 상담 좀 해줄 수 있어?'),
    ('meta-identity',        '너는 뭐야? AI 야 사람이야?'),
    ('persona-interest',     '요즘 본 영화 중에 좋았던 거 있어?'),
    ('persona-emotion',      '오늘 기분 어때?'),
    ('persona-relation',     '너는 새로운 사람 만나면 어떤 느낌이야?'),
    ('common-sense',         '바다는 왜 파란색이야?'),  # 상식 수준
    ('persona-everyday',     '점심 뭐 먹을지 추천해줘'),
]


async def ask(client: httpx.AsyncClient, iid: str, q: str) -> dict:
    response_parts: list[str] = []
    full_response = ''
    event_name = None
    stages_seen: list[str] = []
    async with client.stream(
        'POST', f'{BASE}/api/instances/{iid}/turn',
        json={'user_input': q}, timeout=90.0,
    ) as resp:
        if resp.status_code != 200:
            return {'q': q, 'error': f'HTTP {resp.status_code}'}
        async for raw in resp.aiter_lines():
            if raw.startswith('event:'):
                event_name = raw[len('event:'):].strip()
                if event_name not in (None, 'response_chunk') and event_name not in stages_seen:
                    stages_seen.append(event_name)
            elif raw.startswith('data:'):
                data = raw[len('data:'):].lstrip()
                if event_name == 'response_chunk':
                    try:
                        response_parts.append(json.loads(data).get('text', ''))
                    except Exception:
                        pass
                elif event_name == 'done':
                    try:
                        full_response = json.loads(data).get('response', '')
                    except Exception:
                        pass
    return {
        'q': q,
        'response': full_response or ''.join(response_parts),
        'stages': stages_seen,
        'chunk_count': len(response_parts),
    }


async def main():
    iid = sys.argv[1] if len(sys.argv) > 1 else '_default'

    async with httpx.AsyncClient() as client:
        # persona meta
        try:
            meta = await client.get(f'{BASE}/api/instances/{iid}')
            persona = meta.json().get('persona_id', '?')
            print(f'== persona: {persona} (instance={iid}) ==', flush=True)
        except Exception as exc:
            print(f'meta fetch failed: {exc}', flush=True)

        for tag, q in QUESTIONS:
            print(f'\n=== [{tag}] {q}', flush=True)
            try:
                result = await ask(client, iid, q)
            except Exception as exc:
                print(f'  ! error: {exc!r}', flush=True)
                continue
            if 'error' in result:
                print(f'  ! {result["error"]}', flush=True)
                continue
            print(f'  >> {result["response"]}', flush=True)
            print(f'     (stages={result["stages"]}, chunks={result["chunk_count"]})',
                  flush=True)
            # rate limit 회피 (slowapi 10/min on /turn)
            await asyncio.sleep(7)


if __name__ == '__main__':
    asyncio.run(main())
