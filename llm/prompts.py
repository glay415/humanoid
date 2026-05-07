"""Prompt 템플릿 로더 — prompts/<name>.txt 파일을 str.format 으로 렌더링."""
from __future__ import annotations

from pathlib import Path


PROMPTS_DIR = Path(__file__).resolve().parent.parent / 'prompts'


class PromptTemplate:
    def __init__(self, name: str, content: str):
        self.name = name
        self.content = content

    def render(self, **vars) -> str:  # noqa: A002 - 변수명은 의도적
        """Use Python str.format. Missing variables raise KeyError."""
        return self.content.format(**vars)


def load_prompt(name: str) -> PromptTemplate:
    """Load prompts/<name>.txt. Raises FileNotFoundError if missing."""
    path = PROMPTS_DIR / f"{name}.txt"
    if not path.is_file():
        raise FileNotFoundError(f"Prompt template not found: {path}")
    content = path.read_text(encoding='utf-8')
    return PromptTemplate(name=name, content=content)
