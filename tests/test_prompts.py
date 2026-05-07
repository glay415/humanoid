"""prompts/ 로더 테스트."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from llm.prompts import PromptTemplate, load_prompt


def test_load_prompt_existing_template(tmp_path: Path):
    pdir = tmp_path / "prompts"
    pdir.mkdir()
    (pdir / "demo.txt").write_text("hello {name}", encoding='utf-8')

    with patch('llm.prompts.PROMPTS_DIR', pdir):
        tpl = load_prompt("demo")
    assert isinstance(tpl, PromptTemplate)
    assert tpl.name == "demo"
    assert tpl.render(name="world") == "hello world"


def test_load_prompt_missing_raises(tmp_path: Path):
    pdir = tmp_path / "prompts"
    pdir.mkdir()
    with patch('llm.prompts.PROMPTS_DIR', pdir):
        with pytest.raises(FileNotFoundError):
            load_prompt("missing_template")


def test_render_missing_var_raises_key_error():
    tpl = PromptTemplate(name="t", content="hi {a} and {b}")
    with pytest.raises(KeyError):
        tpl.render(a="x")


def test_render_with_all_vars():
    tpl = PromptTemplate(name="t", content="user={user_input} mood={mood}")
    out = tpl.render(user_input="hello", mood="calm")
    assert out == "user=hello mood=calm"
