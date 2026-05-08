"""휴머노이드 인스턴스 매니저 — 페르소나 기반 spawn / list / get / delete / reset.

각 인스턴스는 자기만의 디스크 영역 (./instances/{id}/) 을 가진다:
  temperament.yaml — jittered 페르소나 설정
  metadata.json     — UI 카드용 메타
  state.json        — RAM 상태 스냅샷 (state_serializer 사용)
  chroma_db/        — VectorDB
  prospective.db    — SQLite 큐

spawn 시 build_full_orchestrator(config_path=temperament.yaml, storage_root=...) 로
풀 오케스트레이터를 만들고 self_model.narrative 를 페르소나 narrative_seed 로 덮는다.
"""
from __future__ import annotations

import datetime as _dt
import json
import random
import shutil
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

from storage.jitter import apply_jitter
from ui.backend import personas as _personas
from ui.backend.state_serializer import (
    restore_orchestrator,
    serialize_orchestrator,
)


# 기본 인스턴스 루트 — 인스턴스 매니저가 spawn 한 모든 디렉토리의 부모.
INSTANCES_ROOT = Path('./instances')

# 기본 인스턴스 ID — legacy /api/turn /api/state /api/reset 호환.
DEFAULT_INSTANCE_ID = '_default'


# ---------------------------------------------------------------------------
# 메타데이터
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return (
        _dt.datetime.now(_dt.timezone.utc)
        .replace(microsecond=0, tzinfo=None)
        .isoformat() + 'Z'
    )


@dataclass
class InstanceMetadata:
    """인스턴스 카드 메타. metadata.json 에 그대로 저장."""
    instance_id: str
    display_name: str
    persona_id: str
    jitter: float
    jitter_seed: int
    created_at: str
    last_active: str
    turn_number: int = 0
    last_mood: dict = field(default_factory=lambda: {'valence': 0.0, 'arousal': 0.0})

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> 'InstanceMetadata':
        return cls(
            instance_id=str(data['instance_id']),
            display_name=str(data.get('display_name', data['instance_id'])),
            persona_id=str(data['persona_id']),
            jitter=float(data.get('jitter', 0.0)),
            jitter_seed=int(data.get('jitter_seed', 0)),
            created_at=str(data.get('created_at', _now_iso())),
            last_active=str(data.get('last_active', _now_iso())),
            turn_number=int(data.get('turn_number', 0)),
            last_mood=dict(data.get('last_mood') or {'valence': 0.0, 'arousal': 0.0}),
        )


# ---------------------------------------------------------------------------
# InstanceManager
# ---------------------------------------------------------------------------


class InstanceManager:
    """디스크 + 메모리에서 다중 인스턴스를 관리한다."""

    def __init__(
        self,
        root: Path | str = INSTANCES_ROOT,
        llm_client_factory=None,
    ):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        # In-memory cache: 살아있는 오케스트레이터.
        self._live: dict[str, Any] = {}
        self._meta_cache: dict[str, InstanceMetadata] = {}
        # LLM 클라이언트를 테스트에서 갈아끼우려는 훅. None 이면 build_full_orchestrator 가
        # 자체 LLMClient() 를 만든다.
        self._llm_client_factory = llm_client_factory

    # ------------------------------------------------------------------ paths

    def instance_dir(self, instance_id: str) -> Path:
        return self.root / instance_id

    def _meta_path(self, instance_id: str) -> Path:
        return self.instance_dir(instance_id) / 'metadata.json'

    def _state_path(self, instance_id: str) -> Path:
        return self.instance_dir(instance_id) / 'state.json'

    def _temperament_path(self, instance_id: str) -> Path:
        return self.instance_dir(instance_id) / 'temperament.yaml'

    # ------------------------------------------------------------------ build

    def _build_orchestrator(self, instance_id: str):
        """temperament.yaml + storage_root 으로 풀 오케스트레이터 조립."""
        from main import build_full_orchestrator
        llm = self._llm_client_factory() if self._llm_client_factory else None
        return build_full_orchestrator(
            config_path=self._temperament_path(instance_id),
            llm_client=llm,
            storage_root=self.instance_dir(instance_id),
        )

    # ------------------------------------------------------------------ spawn

    def spawn(
        self,
        persona_id: str,
        display_name: str | None = None,
        jitter: float = 0.3,
        jitter_seed: int | None = None,
        instance_id: str | None = None,
    ) -> InstanceMetadata:
        """새 인스턴스 생성. 메타데이터 반환.

        Args:
            persona_id: PERSONAS_DIR/<persona_id>.yaml 키.
            display_name: 사용자가 지정한 이름. None 이면 "{persona.display_name}-{short_id}".
            jitter: 0.0 = 페르소나 그대로. 1.0 = baselines ±0.1 / drives ±0.05.
            jitter_seed: 재현성용 시드. None 이면 random.
            instance_id: 명시적 ID 지정 (예: '_default'). None 이면 uuid4.
        """
        persona = _personas.get_persona(persona_id)
        # 1. id / seed 결정
        if instance_id is None:
            instance_id = uuid.uuid4().hex
        if jitter_seed is None:
            jitter_seed = random.randint(0, 2**31 - 1)

        # 2. 페르소나 yaml 로드 후 jitter 적용
        raw = _personas.load_persona_yaml(persona_id)
        jittered = apply_jitter(raw, jitter=float(jitter), seed=int(jitter_seed))

        # 3. 디렉토리 생성 + temperament.yaml 작성
        idir = self.instance_dir(instance_id)
        idir.mkdir(parents=True, exist_ok=True)
        with open(self._temperament_path(instance_id), 'w', encoding='utf-8') as f:
            yaml.safe_dump(jittered, f, allow_unicode=True, sort_keys=False)

        # 4. display_name 결정
        if not display_name:
            display_name = f"{persona.display_name}-{instance_id[:6]}"

        # 5. 오케스트레이터 빌드 + narrative_seed 적용
        orch = self._build_orchestrator(instance_id)
        if persona.narrative_seed and orch.self_model is not None:
            orch.self_model.update({'narrative': persona.narrative_seed})

        # 6. 메타 작성 + 캐시
        now = _now_iso()
        meta = InstanceMetadata(
            instance_id=instance_id,
            display_name=display_name,
            persona_id=persona_id,
            jitter=float(jitter),
            jitter_seed=int(jitter_seed),
            created_at=now,
            last_active=now,
            turn_number=0,
            last_mood={'valence': 0.0, 'arousal': 0.0},
        )
        self._write_metadata(meta)
        self._live[instance_id] = orch
        self._meta_cache[instance_id] = meta

        # 7. 초기 상태도 한 번 저장해 둔다 (deterministic reset 용 baseline 은 yaml 자체).
        self.save_state(instance_id)
        return meta

    # ------------------------------------------------------------------ list / get

    def list(self) -> list[InstanceMetadata]:
        """디스크의 모든 인스턴스 메타. last_active desc 정렬."""
        out: list[InstanceMetadata] = []
        if not self.root.exists():
            return out
        for child in self.root.iterdir():
            if not child.is_dir():
                continue
            meta_path = child / 'metadata.json'
            if not meta_path.exists():
                continue
            try:
                with open(meta_path, 'r', encoding='utf-8') as f:
                    meta = InstanceMetadata.from_dict(json.load(f))
            except (json.JSONDecodeError, OSError, KeyError):
                continue
            out.append(meta)
            self._meta_cache[meta.instance_id] = meta
        out.sort(key=lambda m: m.last_active, reverse=True)
        return out

    def exists(self, instance_id: str) -> bool:
        return self._meta_path(instance_id).exists()

    def get(self, instance_id: str):
        """라이브 오케스트레이터 반환. 없으면 디스크에서 복원 시도."""
        if instance_id in self._live:
            return self._live[instance_id]
        if not self.exists(instance_id):
            raise KeyError(f"instance not found: {instance_id}")
        # 디스크에서 복원
        orch = self._build_orchestrator(instance_id)
        # narrative_seed 복원 — state.json 에 self_model 이 있으면 그쪽이 우선.
        meta = self.get_metadata(instance_id)
        try:
            persona = _personas.get_persona(meta.persona_id)
            if persona.narrative_seed and orch.self_model is not None:
                orch.self_model.update({'narrative': persona.narrative_seed})
        except KeyError:
            pass
        # state.json 이 있으면 in-memory 상태 복원
        sp = self._state_path(instance_id)
        if sp.exists():
            try:
                with open(sp, 'r', encoding='utf-8') as f:
                    state_dict = json.load(f)
                restore_orchestrator(orch, state_dict)
            except (json.JSONDecodeError, OSError):
                pass
        self._live[instance_id] = orch
        return orch

    def get_metadata(self, instance_id: str) -> InstanceMetadata:
        if instance_id in self._meta_cache:
            return self._meta_cache[instance_id]
        meta_path = self._meta_path(instance_id)
        if not meta_path.exists():
            raise KeyError(f"instance not found: {instance_id}")
        with open(meta_path, 'r', encoding='utf-8') as f:
            meta = InstanceMetadata.from_dict(json.load(f))
        self._meta_cache[instance_id] = meta
        return meta

    # ------------------------------------------------------------------ mutate

    def update_metadata(self, instance_id: str, **fields) -> InstanceMetadata:
        meta = self.get_metadata(instance_id)
        for key, value in fields.items():
            if hasattr(meta, key):
                setattr(meta, key, value)
        meta.last_active = _now_iso()
        self._write_metadata(meta)
        return meta

    def save_state(self, instance_id: str) -> None:
        if instance_id not in self._live:
            return
        orch = self._live[instance_id]
        state = serialize_orchestrator(orch)
        with open(self._state_path(instance_id), 'w', encoding='utf-8') as f:
            json.dump(state, f, ensure_ascii=False, indent=2, default=str)

    def _write_metadata(self, meta: InstanceMetadata) -> None:
        idir = self.instance_dir(meta.instance_id)
        idir.mkdir(parents=True, exist_ok=True)
        with open(self._meta_path(meta.instance_id), 'w', encoding='utf-8') as f:
            json.dump(meta.to_dict(), f, ensure_ascii=False, indent=2)
        self._meta_cache[meta.instance_id] = meta

    # ------------------------------------------------------------------ delete / reset

    def delete(self, instance_id: str) -> None:
        # 라이브 핸들 정리
        if instance_id in self._live:
            self._live.pop(instance_id, None)
        self._meta_cache.pop(instance_id, None)
        idir = self.instance_dir(instance_id)
        if idir.exists():
            # SQLite 핸들이 GC 안 된 경우를 대비해 Windows 에서도 안전하게 시도.
            try:
                shutil.rmtree(idir)
            except OSError:
                # 두 번째 시도 — 잠시 후
                import gc
                gc.collect()
                shutil.rmtree(idir, ignore_errors=True)

    def reset(self, instance_id: str) -> InstanceMetadata:
        """동일 페르소나 + 동일 jitter_seed 로 결정론적 재생성.

        삭제 → spawn 으로 깨끗한 인스턴스 (state.json/chroma 모두 새 것).
        """
        meta = self.get_metadata(instance_id)
        persona_id = meta.persona_id
        display_name = meta.display_name
        jitter = meta.jitter
        seed = meta.jitter_seed
        self.delete(instance_id)
        return self.spawn(
            persona_id=persona_id,
            display_name=display_name,
            jitter=jitter,
            jitter_seed=seed,
            instance_id=instance_id,
        )

    # ------------------------------------------------------------------ hard reset / wipe

    def hard_reset(self, instance_id: str) -> InstanceMetadata:
        """페르소나 + jitter_seed 는 보존하면서 인스턴스의 모든 영속 스토리지를
        삭제한 뒤 같은 instance_id 로 결정론적 재스폰.

        삭제 대상:
          - chroma_db/        (VectorDB persistent collection)
          - prospective.db    (ProspectiveQueue SQLite)
          - state.json        (직렬화된 in-memory 상태)
          - markers.db        (있다면)
          - storage_data/     (있다면 — legacy 호환)

        보존 대상:
          - instance_id, created_at  (메타 동일성)
          - persona_id, jitter, jitter_seed  (재현 가능한 baselines)
          - display_name

        주의 (Windows): Chroma 의 PersistentClient 가 sqlite3 파일 핸들을 잡고
        있을 수 있으므로 GC 후 ignore_errors=True 로 두 번 시도한다.
        """
        # 1. 메타 백업.
        meta = self.get_metadata(instance_id)
        persona_id = meta.persona_id
        display_name = meta.display_name
        jitter = meta.jitter
        seed = meta.jitter_seed
        created_at = meta.created_at

        # 2. 라이브 오케스트레이터 핸들 정리 — 파일 핸들 release 유도.
        self._live.pop(instance_id, None)
        self._meta_cache.pop(instance_id, None)
        import gc
        gc.collect()

        # 3. 인스턴스 디스크 정리 — 디렉토리 자체는 유지하고 내부 storage 만 비운다.
        idir = self.instance_dir(instance_id)
        for sub in ('chroma_db', 'storage_data'):
            target = idir / sub
            if target.exists():
                try:
                    shutil.rmtree(target)
                except OSError:
                    # Windows + Chroma 의 sqlite 파일 핸들 잔류 케이스: 두 번째 시도.
                    gc.collect()
                    shutil.rmtree(target, ignore_errors=True)
        for fname in ('state.json', 'prospective.db', 'markers.db'):
            fpath = idir / fname
            if fpath.exists():
                try:
                    fpath.unlink()
                except OSError:
                    pass

        # 4. 동일 페르소나 + 동일 seed 로 재스폰.
        new_meta = self.spawn(
            persona_id=persona_id,
            display_name=display_name,
            jitter=jitter,
            jitter_seed=seed,
            instance_id=instance_id,
        )
        # 5. created_at 보존 — spawn 은 새 timestamp 를 찍으므로 덮어쓴다.
        new_meta.created_at = created_at
        new_meta.turn_number = 0
        new_meta.last_mood = {'valence': 0.0, 'arousal': 0.0}
        self._write_metadata(new_meta)
        return new_meta

    def wipe_all(self) -> dict:
        """모든 인스턴스를 삭제하고 캐시를 비운다. {removed: int} 반환.

        legacy /api/turn 등은 이후 첫 호출 시 _default 를 자동 재스폰
        (StateHolder.initialize → MANAGER.get_or_spawn_default).
        """
        # 1. 라이브 핸들 / 메타 캐시 정리.
        self._live.clear()
        self._meta_cache.clear()
        # 2. 디렉토리 카운팅.
        removed = 0
        if self.root.exists():
            for child in self.root.iterdir():
                if child.is_dir():
                    removed += 1
        # 3. 루트 자체를 날리고 빈 디렉토리로 재생성.
        import gc
        gc.collect()
        if self.root.exists():
            try:
                shutil.rmtree(self.root)
            except OSError:
                gc.collect()
                shutil.rmtree(self.root, ignore_errors=True)
        self.root.mkdir(parents=True, exist_ok=True)
        return {'removed': int(removed)}

    # ------------------------------------------------------------------ default helper

    def get_or_spawn_default(self, persona_id: str = 'extrovert_warm') -> Any:
        """legacy /api/turn 호환 — _default 인스턴스 반환. 없으면 spawn."""
        if self.exists(DEFAULT_INSTANCE_ID):
            return self.get(DEFAULT_INSTANCE_ID)
        # _default 는 jitter 0 으로 페르소나 원본을 그대로 따른다.
        self.spawn(
            persona_id=persona_id,
            display_name='기본 인스턴스',
            jitter=0.0,
            jitter_seed=0,
            instance_id=DEFAULT_INSTANCE_ID,
        )
        return self._live[DEFAULT_INSTANCE_ID]
