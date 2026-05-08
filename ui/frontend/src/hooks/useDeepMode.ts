import { useCallback, useEffect, useState } from 'react';

// Wave14E: 심층 시각화 모드 토글. localStorage 영속.
// off = 기본 사이드바, on = 매트릭스 분해 / 고유값 / mood / drift 추가 패널.

const STORAGE_KEY = 'humanoid-deep-mode';

function readInitialDeep(): boolean {
  if (typeof window === 'undefined') return false;
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (stored === '1' || stored === 'true') return true;
    if (stored === '0' || stored === 'false') return false;
  } catch {
    // localStorage may be unavailable.
  }
  return false;
}

export type UseDeepModeResult = {
  deep: boolean;
  toggle: () => void;
  setDeep: (v: boolean) => void;
};

export function useDeepMode(): UseDeepModeResult {
  const [deep, setDeepState] = useState<boolean>(() => readInitialDeep());

  useEffect(() => {
    try {
      window.localStorage.setItem(STORAGE_KEY, deep ? '1' : '0');
    } catch {
      // ignore persistence failures
    }
  }, [deep]);

  const setDeep = useCallback((v: boolean) => {
    setDeepState(v);
  }, []);

  const toggle = useCallback(() => {
    setDeepState((prev) => !prev);
  }, []);

  return { deep, toggle, setDeep };
}
