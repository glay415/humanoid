"""페르소나 카탈로그 로더 — config/personas/*.yaml 을 읽어 메타 + summary 노출.

UI 의 spawn 화면이 5개 카드로 페르소나를 보여주려고 사용한다. summary 는
프론트가 핵심 baseline / 형용사 몇 개만 보여주기 위한 가벼운 dict.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


# 페르소나 yaml 위치 — 이 파일은 ui/backend/personas.py 이므로 두 단계 위가 repo root.
PERSONAS_DIR = Path(__file__).resolve().parent.parent.parent / 'config' / 'personas'


# 페르소나별 핵심 형용사 (UI 카드 부제용). 누락 시 빈 리스트.
_KEY_TRAITS: dict[str, list[str]] = {
    'introvert_thoughtful': ['차분', '깊은 사고', '내향'],
    'extrovert_warm': ['활기', '따뜻함', '외향'],
    'sensitive_empathic': ['예민', '공감', '섬세'],
    'steady_analytical': ['안정', '분석적', '논리'],
    'playful_companion': ['장난', '유머', '경쾌'],
}

# summary 에 노출할 baseline 키 — 너무 많으면 카드가 복잡해짐.
_SUMMARY_BASELINES = (
    'reward', 'arousal', 'excitation', 'inhibition', 'bonding',
)


@dataclass
class PersonaInfo:
    """페르소나 카탈로그 한 항목."""
    id: str
    display_name: str
    description: str
    narrative_seed: str
    summary: dict
    config_path: Path

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'display_name': self.display_name,
            'description': self.description,
            'narrative_seed': self.narrative_seed,
            'summary': dict(self.summary),
        }


def _load_yaml(path: Path) -> dict:
    with open(path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def _build_summary(yaml_dict: dict) -> dict:
    """yaml dict → 카드용 요약 dict.

    {
      'key_baselines': {reward: 0.45, ...},
      'key_traits': ['차분', '깊은 사고', '내향'],
      'drive_ratios': {curiosity: 0.30, ...},
    }
    """
    persona_id = str(yaml_dict.get('persona_id', ''))
    baselines = yaml_dict.get('baselines', {}) or {}
    drives = yaml_dict.get('drive_ratios', {}) or {}
    key_baselines = {
        k: float(baselines[k]) for k in _SUMMARY_BASELINES if k in baselines
    }
    key_traits = list(_KEY_TRAITS.get(persona_id, []))
    return {
        'key_baselines': key_baselines,
        'key_traits': key_traits,
        'drive_ratios': {k: float(v) for k, v in drives.items()},
    }


def _info_from_path(path: Path) -> PersonaInfo:
    data = _load_yaml(path)
    return PersonaInfo(
        id=str(data.get('persona_id') or path.stem),
        display_name=str(data.get('display_name', path.stem)),
        description=str(data.get('description', '')),
        narrative_seed=str(data.get('narrative_seed', '') or '').strip(),
        summary=_build_summary(data),
        config_path=path,
    )


def list_personas(personas_dir: Path | None = None) -> list[PersonaInfo]:
    """카탈로그 전체. id 알파벳 순서 안정 정렬."""
    base = Path(personas_dir) if personas_dir else PERSONAS_DIR
    if not base.exists():
        return []
    items: list[PersonaInfo] = []
    for path in sorted(base.glob('*.yaml')):
        try:
            items.append(_info_from_path(path))
        except (yaml.YAMLError, KeyError, OSError):
            # 손상된 파일은 건너뜀 — UI 가 죽지 않게.
            continue
    items.sort(key=lambda p: p.id)
    return items


def get_persona(persona_id: str, personas_dir: Path | None = None) -> PersonaInfo:
    """단일 페르소나 조회. 없으면 KeyError."""
    base = Path(personas_dir) if personas_dir else PERSONAS_DIR
    candidate = base / f'{persona_id}.yaml'
    if not candidate.exists():
        raise KeyError(f"persona not found: {persona_id}")
    return _info_from_path(candidate)


def load_persona_yaml(persona_id: str, personas_dir: Path | None = None) -> dict:
    """전체 yaml dict 그대로 반환 (jitter / orchestrator build 용)."""
    info = get_persona(persona_id, personas_dir)
    return _load_yaml(info.config_path)
