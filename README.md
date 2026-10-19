# Local Model Quality Kit + A/B Benchmark

Claude Code에 로컬 모델을 연결해 쓸 때, 품질 개선 키트의 적용 전/후를 비교하는
**실행 가능한 소규모 파일럿 벤치마크**입니다. Python 표준 라이브러리만 사용합니다.

- `quality-kit/`: 고정 작업 지침, 검증 훅, 로그 압축 도구, 전용 실행기.
- `bench.py`: 동일 출발점 생성 → 명시적 모델 실행 → 외부 채점 → 비교 리포트.
- `grader.py`: 모델 작업 폴더 밖에서 실행하는 추가 기능/회귀 검사.
- `tasks.py`: 한국어 요구사항, 결함이 있는 초기 코드, 공개 테스트, 채점기 검증용 정답.
- `reporting.py`: CSV/JSON/Markdown 집계와 조건명을 숨긴 수동 리뷰 묶음.

**실제 모델의 성능 개선 수치는 아직 측정하지 않았습니다.** 자체 테스트 통과는 실행기와
채점기의 동작 검증이지, 로컬 모델의 정확도 향상을 증명하는 결과가 아닙니다.
공개 표준 벤치마크가 아니라 간단한 Python 작업으로 만든 시작용 문제군입니다.

## 요구 환경

- macOS 또는 Linux, Python 3.10 이상.
- 실제 모델 실행 시에만 Claude Code 필요.
- 로컬 모델을 제공하는 **Anthropic 호환 API 또는 로컬 변환 프록시**.
- API 인증은 기존 환경변수로 제공. 이 저장소에 토큰/비밀을 넣지 마세요.

OpenAI 호환 `/v1/chat/completions` 주소만으로 Claude Code가 직접 연결되는 것은 아닙니다.
이미 Claude Code에서 로컬 모델 호출이 되는 환경을 전제로 합니다.
실행기는 실수로 클라우드 모델을 호출하지 않도록 loopback URL만 허용합니다.
로컬 프록시 자체가 외부로 전달하는지는 실행기가 판별할 수 없습니다.

## 1. 모델 없이 자체 검증

저장소 루트에서:

```bash
./scripts/run_tests.sh
```

`test_benchmark.py`는 출발점 동일성, 초기 코드 거부/정답 통과, 테스트 변경 감지,
미실행 결과를 성공률로 만들지 않기, 로컬 주소/실행 동의 검사를 확인합니다.
`quality-kit/test_kit.py`는 훅 프로토콜, 타임아웃, 쓰기 확인과 실행기 동작을 확인합니다.
실제 모델 호출/다운로드/패키지 설치는 하지 않습니다.

## 2. 비교용 작업 생성

```bash
python3 bench.py --runs ./runs/pilot prepare --repeats 3
```

문제는 중복 제거, 페이지네이션, 금액 반올림, 예외 재시도, 구간 병합입니다.
각 문제를 baseline/full 조건으로 반복할 작업 폴더를 만들고 순서를 고정 seed로 섞습니다.
기존 결과가 있는 출력 폴더는 덮어쓰지 않습니다.

```text
runs/pilot/
  manifest.json                # 실행 순서
  <task>-<condition>-r<N>/
    workspace/
      solution.py             # 유일한 수정 허용 코드
      TASK.md                 # 두 조건에서 동일한 요청
      tests/test_public.py    # 작업 중 사용 가능한 공개 테스트
    kit/                      # full 조건 전용; workspace 바깥
    settings.json
    meta.json                 # 시작 파일 해시
```

평가용 추가 검사와 정답은 workspace 안으로 복사하지 않습니다.
단, 이는 보안 샌드박스가 아닙니다. Bash 권한이 있는 에이전트는 형제 폴더나 공개 저장소를
읽을 수 있습니다. 적대적 평가/출판용 벤치마크에는 별도 컨테이너와 파일시스템·네트워크
격리가 필요합니다. 이 코드 자체와 정답은 공개되어 있어 학습 오염 가능성도 있습니다.

## 3. 실제 호출 전 dry run

다음 모델명과 포트는 **형식 예시**입니다. 본인이 사용하는 값으로 바꾸세요.

```bash
python3 bench.py --runs ./runs/pilot run \
  --model YOUR_LOCAL_MODEL \
  --base-url http://127.0.0.1:YOUR_PORT \
  --model-notes '모델 파일/양자화/서버 버전/생성 옵션' \
  --timeout 300
```

`--execute`가 없으면 명령과 작업 위치만 출력하며 모델을 호출하지 않습니다.
포트에는 실제 숫자를 넣어야 합니다. `/v1` 유무는 사용 중인 Anthropic 호환 프록시 설정에 맞추세요.

## 4. 실제 A/B 실행 — 사용자가 명시적으로 시작

```bash
python3 bench.py --runs ./runs/pilot run \
  --model YOUR_LOCAL_MODEL \
  --base-url http://127.0.0.1:YOUR_PORT \
  --model-notes '모델 파일/양자화/서버 버전/생성 옵션' \
  --timeout 300 \
  --execute
```

실행 순서에 따라 새 세션/새 작업 폴더에서 순차 호출합니다.
`--id dedupe-baseline-r1`처럼 특정 실행만 선택할 수 있습니다.
이미 시작한 작업 폴더는 재사용하지 않습니다. 재실험은 새 `--runs`에서 시작하세요.
중간에 멈춘 배치는 manifest의 아직 시작하지 않은 ID를 골라 `--id`로 실행하세요.

- 두 조건에 동일한 사용자 요청과 시간 예산 제공.
- baseline은 이 실험의 설정에서 `disableAllHooks: true`.
- full은 고정 지침 + 키트 훅; 공개 테스트 명령 자동 등록.
- 실행별 CLAUDE_CONFIG_DIR 분리, 사용자/프로젝트 설정 로딩 제외, auto-memory 비활성, 사용자 MCP 제외.
- 상위 CLAUDE.md/CLAUDE.local.md/.claude/rules를 탐지하고 해시를 기록합니다.
  발견되면 기본적으로 실제 실행을 거부합니다. 깨끗한 경로를 사용하거나, 영향을 감수하는
  실험에 한해 --allow-ancestor-instructions로 명시적으로 허용하세요.
- 두 조건 모두 acceptEdits로 폐기 가능한 작업 폴더의 편집을 허용하며,
  python3/현재 Python 실행 파일의 unittest 명령만 Bash 자동 승인 목록에 추가합니다.
  전체 권한 우회 플래그는 사용하지 않습니다. 그 외 명령은 거부될 수 있으므로 로그를 확인하세요.
- 조직 관리 정책과 상위 지침을 완전히 격리하는 OS 샌드박스는 아닙니다.
- API 키/로컬 모델 연결에 필요한 설정은 **환경변수**로 제공해야 함.
- 시스템 프롬프트를 실행 도중 변경하거나 동적 도구 차단을 하지 않음.
- baseline/full 구성 파일의 훅 차이는 의도된 실험 조건임.
- 외부 최종 채점 시간은 에이전트 실행 시간에 포함하지 않음; 작업 중 훅 시간은 포함.

`execution.json`에는 실제 호출 정보/종료 상태/시간/서버가 보고한 usage를 저장합니다.
서버/CLI가 토큰 정보를 제공하지 않으면 토큰 수는 비어 있습니다. 추정하지 않습니다.
`agent-output.json`에는 원본 출력이 있어 개인정보/비밀이 포함될 수 있습니다.

## 5. 독립 채점과 보고서

```bash
python3 bench.py --runs ./runs/pilot evaluate
python3 bench.py --runs ./runs/pilot report
```

생성 파일:

- `evaluation.json`: 실행별 기능 검사와 공개 테스트/요청 파일 변경 감지.
- `results.csv`: 실행별 상태/성공/시간/토큰.
- `summary.json`, `summary.md`: 조건별 성공률, 중앙 실행 시간, 대응 승패.
- `blind-review/`: 조건명 없는 코드/diff/최종 응답/근거/채점 양식.
- `review-key.json`: 블라인드 ID와 원래 조건의 대응표. **리뷰어에게 전달 금지**.

최종 성공은 독립 기능 검사 통과 + 보호 파일 변경 없음 + 실제 에이전트 정상 종료입니다.
CLI/API 오류와 타임아웃은 실패입니다. 독립 평가 전인 실행은 pending으로 분리합니다.
모델을 한 번도 호출하지 않은 결과는 성공률 `null`이며 성능 측정으로 집계하지 않습니다.
평가만 수동으로 실행한 경우 기능 판정은 나오지만 모델 성능 측정에는 포함되지 않습니다.

채점은 candidate Python 코드를 실제 실행합니다. 신뢰할 수 없는 코드는 격리 환경에서 실행하세요.
시간 제한은 있지만 CPU/메모리/디스크/네트워크 보안 격리는 하지 않습니다.

## 정성 평가

`blind-review/rubric.md`와 `scores.template.csv`를 사용해 사람이 점수를 입력합니다.
요구사항 충족/변경 범위/유지보수성/보고 정확성을 분리합니다. 점수는 자동 생성하지 않습니다.
이번 문제는 테스트 변경 금지이므로 테스트 작성 능력은 N/A이며 별도 과제군이 필요합니다.
전체 도구 transcript를 수집하지 않으므로 일부 검증 주장은 근거 부족으로 남을 수 있습니다.
반복 report는 기존 수동 점수를 보존하면서 새 블라인드 ID 행을 자동 추가합니다.
채점 결과는 workspace와 실행 기록의 해시에 묶입니다. 이후 코드/실행 기록이 달라지면
기존 채점은 집계에서 제외되고 다시 evaluate해야 합니다. SkipTest는 통과로 인정하지 않습니다.
수정 허용 파일 외의 추가/삭제/변경도 감지합니다. 캐시 폴더만 무결성 비교에서 제외합니다.

## 해석할 때 주의

- 성공률과 시간 증가를 같이 보세요. full이 재시도에 쓰는 시간도 비용입니다.
- 대응 승패는 동일 문제/반복의 두 조건이 모두 실행·평가된 쌍만 계산합니다.
- 작은 문제군의 반복을 모두 독립된 새 문제처럼 취급하지 마세요.
- 자동 신뢰구간/유의성 주장, LLM 심사, 거짓 완료 자동 판정, ablation은 아직 미구현입니다.
- 같은 머신에서 병렬 추론하지 않고, 서버 워밍업 정책/온도/컨텍스트/양자화를 고정하세요.
- 현재 문제는 짧고 Python 중심이라 긴 로그 압축/장기 상태 관리의 효과를 충분히 측정하지 못합니다.
  실제 코드베이스·다중 파일·긴 로그 문제를 추가한 뒤 일반화 여부를 확인해야 합니다.
- think=false/KV 캐시 포킹/서버 최적화를 구현하거나 검증한 패키지는 아닙니다.

## 참고

- 아이디어 소개: https://javaexpert.tistory.com/1704
- Claude Code 훅 규약: https://code.claude.com/docs/en/hooks
- CLI 규약: https://code.claude.com/docs/en/cli-reference

실험 출력/토큰/환경변수/인증 파일은 Git에 올리지 않습니다. `.gitignore`에 기본 제외했습니다.
