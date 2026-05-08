"""humanoid scripts — CLI / dev utilities.

`scripts` 가 정식 패키지로 선언되어야 분석 도구 (analyze + analyze_charts)
간 상호 import 와 테스트에서의 `from scripts import analyze` 가 정상 동작한다.
설치 환경에 우연히 동명의 third-party 패키지가 있어도 PROJECT_ROOT 가 sys.path
앞에 오면 본 패키지가 우선된다.
"""
