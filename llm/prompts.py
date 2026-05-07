"""Prompt loader skeleton — 실제 구현은 다음 커밋에서."""
from __future__ import annotations

from pathlib import Path


PROMPTS_DIR = Path(__file__).resolve().parent.parent / 'prompts'


class PromptTemplate:
    def __init__(self, name: str, content: str):
        self.name = name
        self.content = content

    def render(self, **vars) -> str:  # noqa: A002 - 템플릿 변수 인자명 유지
        raise NotImplementedError("render impl arrives in next commit")


def load_prompt(name: str) -> PromptTemplate:
    raise NotImplementedError("load_prompt impl arrives in next commit")
