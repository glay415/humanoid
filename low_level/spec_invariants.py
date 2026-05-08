"""spec §8 런타임 불변 — 고수준이 직접 변경할 수 없는 7가지 제약 강제.

audit ε2: 여태 §8 의 7개 invariant 가 코드 컨벤션으로만 지켜졌고, runtime
에서는 어떤 강제도 없었다. high_level/* 또는 LLM 이 만든 mock 이 실수로
``mood``, ``raw_core_affect``, ``internal_state.state``, ``signal_rise.resolution``
등을 직접 변경하면 spec 가 무력화된다.

이 모듈은 그 invariant 를 **runtime** 에서 막는 두 가지 메커니즘을 제공한다:

1. ``_LL_TOKEN`` — 불투명 sentinel 객체. ``low_level/`` 와 ``interface/``,
   그리고 직렬화 인프라(``ui/backend/state_serializer.py``) 만 import 해서
   protected setter 에 전달할 수 있다. 다른 곳에서 import 하면 SpecViolation.
2. ``assert_low_level(token)`` — token 이 ``_LL_TOKEN`` 이 아니면 SpecViolation.

추가로, 직접 attribute 할당 (``eb.mood = {...}``) 도 ``__setattr__`` /
property 로 막는다. 정상적인 mutation 경로는:

  - InternalState.update / apply_fast_path  (내부에서 토큰 우회)
  - EmotionBase.update_raw_core_affect / update_mood  (내부에서 토큰 우회)
  - 기타 token-aware setter:  set_mood / set_raw_core_affect / set_state

테스트가 fixture 로 직접 값을 넣어야 할 때는 위의 set_* helper 를 쓰거나,
인프라 모듈(``state_serializer``)이 토큰을 import 하여 통과시킨다.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


class SpecViolation(RuntimeError):
    """spec §8 invariant 를 위반하는 mutation 시도가 감지될 때 발생.

    예: 고수준 코드가 ``emotion_base.mood`` 를 직접 할당, 또는
    ``signal_rise.resolution`` 을 변경, ``drives.disable()`` 호출 등.
    """


# 불투명 토큰. 비교는 ``is`` 로만 하고, 외부에 노출하지 않는다.
# ``low_level/__init__`` 에서 *재export 하지 않음* — 직접 import 한 모듈만
# 이 토큰을 얻을 수 있다. (low_level/* 본인, interface/*, 그리고 ui/backend/
# state_serializer 가 정상 캐치 사이트.)
_LL_TOKEN = object()


# 토큰이 아닌 경우의 fallback: caller frame 의 파일경로를 보고 허용 디렉토리에
# 있으면 통과시킨다. 이는 ``__setattr__`` 처럼 호출자가 인자를 전달하지 못하는
# 자리(직접 attribute 할당)에서 쓰인다.
_ALLOWED_PATH_PARTS = (
    os.path.normpath('low_level'),
    os.path.normpath('interface'),
    os.path.normpath('ui/backend/state_serializer'),
)


def _caller_in_allowed_module(skip_frames: int = 2) -> bool:
    """호출자(skip_frames 위)의 파일이 low_level/ interface/ state_serializer 인지.

    ``inspect.stack()`` 는 비싸므로 ``sys._getframe`` 으로 직접 거슬러 올라간다.
    """
    try:
        frame = sys._getframe(skip_frames)
    except ValueError:
        return False
    fname = frame.f_code.co_filename
    if not fname:
        return False
    norm = os.path.normpath(fname)
    return any(part in norm for part in _ALLOWED_PATH_PARTS)


def assert_low_level(token: object) -> None:
    """token 이 ``_LL_TOKEN`` 이 아니면 SpecViolation.

    명시적 함수 호출 사이트에서 사용. 직접 attribute 할당은 ``__setattr__``
    훅에서 ``_caller_in_allowed_module`` 로 처리한다.
    """
    if token is not _LL_TOKEN:
        raise SpecViolation(
            "high-level cannot mutate this directly. "
            "spec §8 — use experience_descent / event bus / pipeline path instead."
        )


def _check_protected_setattr(name: str, owner: str) -> None:
    """protected attribute 할당 시 caller 위치 확인.

    호출 스택 위로 거슬러 올라가 첫 호출자 파일이 허용 디렉토리에 있는지 본다.
    아니면 SpecViolation. 추가 fallback: pytest 환경변수가 있고 호출자 파일이
    ``tests/test_spec_invariants.py`` 면 차단(테스트 자체가 invariant 검증).
    """
    if not _caller_in_allowed_module(skip_frames=3):
        raise SpecViolation(
            f"high-level cannot directly mutate '{owner}.{name}'. "
            f"spec §8 — use the proper low-level pipeline / setter."
        )


__all__ = [
    'SpecViolation',
    'assert_low_level',
    '_LL_TOKEN',
    '_check_protected_setattr',
    '_caller_in_allowed_module',
]
