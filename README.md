# 로컬 모델용 최소 지침 + A/B 벤치마크

> **실제 Wiki agent vs 실제 OpenCode를 Windows에서 직접 테스트:**
> [실행 스크립트·설치·명령](docs/wiki-vs-opencode.md). `python wiki_benchmark.py`는
> 모델 호출 없는 preflight이며 실제 실행에는 `--execute`가 필요합니다.
> 이 별도 runner는 Python 추가 패키지와 OpenCode 1.2.27이 필요합니다.

기존 Claude Code·Codex에서 읽는 프로젝트 지침 파일에 짧은 공통 지침을 설치합니다.
기본 방식은 **MD 파일만 배포**하는 것입니다. 별도 에이전트, 자동 검증 훅, 모델 연결 설정을 추가하지 않습니다.
Claude Code용 벤치마크로 추가 공통 지침이 없는 `baseline`과 최소 지침만 추가한 `minimal`을 비교할 수 있습니다.

품질 향상이나 속도 개선은 아직 입증하지 않았습니다. 이전 full 방식에서 더 느린 실행과 타임아웃이
관찰되었지만, 정량적인 개선·악화 수치를 확정한 결과는 아닙니다. 자체 테스트 통과도 모델 성능의 증거가 아닙니다.

## 1. 실행 환경

아래 Python 명령은 저장소 루트에서 실행합니다. Windows PowerShell에서도 명령을 한 줄씩 복사할 수 있습니다.

```powershell
python --version
```

- Python 3.10 이상이며 추가 Python 패키지는 필요 없습니다.
- Windows 네이티브, macOS, Linux를 대상으로 합니다. WSL은 필요 없습니다.
- Windows에서 `python`이 동작하면 `py`는 없어도 됩니다. macOS/Linux에서 `python3`만 되면 바꿔 쓰세요.
- 자체 테스트와 벤치마크 dry-run에는 Claude·Codex·모델 서버가 필요 없습니다.
- 실제 벤치마크에는 평소 모델 호출이 되는 Claude Code가 필요합니다. 기존 CC Switch 연결을 사용할 수 있습니다.
- Claude 실행기는 native EXE와 공식 npm `.cmd`/`.bat` 설치를 지원합니다. JS 진입점에는 Node가 필요합니다.
  사용자 정의 배치·PowerShell 래퍼의 추가 동작은 지원하지 않습니다.

이 도구는 모델 서버나 인증을 설치하지 않습니다. Claude Code에는 Anthropic 호환 API 또는 변환 프록시가
필요하며, OpenAI 호환 `/v1/chat/completions` 주소만으로 직접 연결되지는 않습니다.
Codex 지원은 **지침 배포와 수동 사용**까지입니다. `run`·`evaluate`·`report`는 Claude 벤치마크용입니다.

## 2. 먼저 자체 테스트와 dry-run

### 자체 테스트: 모델 호출 없음

```powershell
python scripts/run_tests.py
```

벤치마크·실행기·지침 배포·레거시 키트의 자체 검사를 실행합니다. 모델 다운로드나 호출은 하지 않습니다.
통과는 코드의 검사 결과이지, 모델 연결·지침 준수·캐시 적중·품질 향상을 확인한 결과가 아닙니다.

### 선택된 Claude 경로 확인: 모델 호출 없음

```powershell
python quality-kit/launch.py --check
```

선택된 실행 경로·`command_prefix`·실행 프로필을 확인합니다. 모델 연결이나 인증 성공은 검사하지 않습니다.
기본 프로필은 기존 Claude를 그대로 실행하는 방식이며 키트 프롬프트나 훅을 추가하지 않습니다.

### 기본 비교 준비와 명령 미리보기: 모델 호출 없음

```powershell
python bench.py --runs ./runs/quick-01 prepare --repeats 1
python bench.py --runs ./runs/quick-01 run --id dedupe-baseline-r1 --inherit-cli-config
python bench.py --runs ./runs/quick-01 run --id dedupe-minimal-r1 --inherit-cli-config
```

`prepare`는 모든 문제의 baseline/minimal 작업 폴더를 만듭니다. 위에서는 중복 제거 문제만 선택합니다.
`run`은 `--execute`가 없으면 dry-run입니다. 출력의 명령·작업 위치·상위 지침을 검토하세요.
기존 결과는 덮어쓰지 않습니다. 다시 시도할 때는 `quick-02`처럼 새 `--runs` 경로를 사용하세요.

## 3. 선택 사항: 한 문제의 실제 A/B

**아래 `--execute` 명령부터 실제 모델을 호출합니다.** `--inherit-cli-config`는 기존 Claude 설정·인증·
환경변수·MCP·개인 지침의 영향을 유지합니다. CC Switch가 선택한 연결이 클라우드이면 클라우드를
호출할 수 있으므로, 로컬 연결인지 먼저 확인하세요. 완전히 격리된 비교는 아닙니다.

```powershell
python bench.py --runs ./runs/quick-01 run --id dedupe-baseline-r1 --inherit-cli-config --execute
python bench.py --runs ./runs/quick-01 run --id dedupe-minimal-r1 --inherit-cli-config --execute
python bench.py --runs ./runs/quick-01 evaluate --id dedupe-baseline-r1
python bench.py --runs ./runs/quick-01 evaluate --id dedupe-minimal-r1
python bench.py --runs ./runs/quick-01 report
```

각 실행은 새 workspace·새 세션을 사용하며 기본 시간 제한은 실행별 300초입니다.
`evaluate`는 후보 코드를 실행해 채점하고, `report`는 결과를 집계합니다. 둘 다 모델은 호출하지 않습니다.
`runs/quick-01/summary.md`와 `results.csv`를 확인하세요. 선택하지 않은 문제는 미실행으로 남습니다.
한 문제의 결과만으로 품질 향상을 결론 내리지 마세요. 이미 시작한 ID는 재실행하지 않습니다.

### 무엇을 비교하나요?

| 조건 | 프로젝트 지침 | 벤치마크 훅·자동 메모리 |
| --- | --- | --- |
| `baseline` | 최소 지침 없음 | 비활성화 |
| `minimal` | `minimal-kit/INSTRUCTIONS.md`를 `workspace/CLAUDE.md`로 배포 | 비활성화 |
| `full` | 예전 고정 프롬프트·키트 훅 | 실험용 레거시 방식 |

baseline/minimal의 `TASK.md`와 시작 코드는 같습니다. minimal에는 키트를 복사하지 않고
`--append-system-prompt`도 사용하지 않습니다. 두 조건 모두 사용자 훅까지 비활성화합니다.
이는 벤치마크용 제어이며, 실제 프로젝트에 MD를 설치하는 작업은 훅·자동 메모리 설정을 바꾸지 않습니다.
조직 관리 정책을 우회하지도 않습니다.

## 4. 내 프로젝트에 최소 지침 설치

모델 실험 없이 지침만 쓰려면 아래 명령으로 시작하세요. `C:/work/my-project`는 실제 프로젝트 경로로 바꾸세요.
macOS/Linux에서도 같은 옵션에 해당 환경의 경로를 지정합니다.

```powershell
# 미리보기: 파일 변경과 모델 호출 없음
python scripts/install_instructions.py --target "C:/work/my-project" --cli both

# 적용: CLAUDE.md와 AGENTS.md에 관리 블록 설치
python scripts/install_instructions.py --target "C:/work/my-project" --cli both --apply
```

- `--cli claude`는 `CLAUDE.md`, `--cli codex`는 `AGENTS.md`, `--cli both`는 두 파일을 대상으로 합니다. 기본값은 `both`입니다.
- 공통 원본은 `minimal-kit/INSTRUCTIONS.md` 하나입니다. 같은 원본으로 두 CLI용 관리 블록을 갱신합니다.
- 기존 파일의 관리 블록 밖 내용은 보존합니다. 같은 지침을 다시 적용해도 블록이 중복되지 않습니다.
- 심볼릭 링크 대상이나 충돌·손상된 관리 마커가 있으면 쓰기를 거부합니다. 파일을 검토한 뒤 다시 시도하세요.
- `.claude/settings.json`, 인증, CC Switch 설정, 모델 매핑을 변경하지 않습니다. 전역 지침을 설치하지도 않습니다.
- 현재 작업 단계·진행률·임시 메모 같은 동적 상태를 지침 파일에 기록하지 않습니다.

설치 후 **대상 프로젝트로 이동해** 평소처럼 `claude` 또는 `codex`로 새 세션을 시작하세요.
`quality-kit/` 복사나 전용 실행기는 필요 없습니다. CLI가 프로젝트 지침을 읽는 규칙·상위 지침의 영향은
각 CLI 설정에 따릅니다. 설치 성공만으로 모델이 읽거나 준수했다는 사실을 증명하지는 않습니다.

제거도 기본은 미리보기이며, `--apply`를 붙이면 선택한 파일의 관리 블록만 제거합니다.

```powershell
python scripts/install_instructions.py --target "C:/work/my-project" --cli both --remove
python scripts/install_instructions.py --target "C:/work/my-project" --cli both --remove --apply
```

수동 사용과 레거시 실행기 차이는 [지침 배포 가이드](quality-kit/README.ko.md)를 참고하세요.
설치된 지침이 있는 프로젝트에서 `launch.py --baseline`을 실행해도 그 MD가 무효화되지는 않습니다.

## 5. 반복 실험과 레거시 full

빠른 A/B가 동작하면 새 폴더에서 전체 문제를 반복합니다. 문제는 중복 제거, 페이지네이션,
금액 반올림, 예외 재시도, 구간 병합입니다.

```powershell
python bench.py --runs ./runs/pilot-01 prepare --repeats 3
python bench.py --runs ./runs/pilot-01 run --inherit-cli-config
# 다음 명령은 실제 모델 호출
python bench.py --runs ./runs/pilot-01 run --inherit-cli-config --execute
python bench.py --runs ./runs/pilot-01 evaluate
python bench.py --runs ./runs/pilot-01 report
```

실행 순서는 고정 seed로 섞습니다. 모델·양자화·서버 버전·생성 옵션·워밍업·시간 예산을 고정하고
동시 추론을 피하세요. `run --model-notes "환경 설명"`으로 조건을 기록할 수 있습니다.
중단 후에는 실행 기록을 확인하고 아직 시작하지 않은 ID만 `--id`로 선택하세요.

full은 기본 준비 대상이 아닙니다. 예전 실험 재현에만 명시적으로 선택하세요.

```powershell
python bench.py --runs ./runs/legacy-01 prepare --conditions baseline full --repeats 1
# 세 조건을 함께 준비할 수도 있음
python bench.py --runs ./runs/three-01 prepare --conditions baseline minimal full --repeats 1
```

기존 full 결과도 `report`로 읽을 수 있습니다. full의 광범위한 도구 훅과 Stop 테스트·재시도는 추가 비용을
만듭니다. Stop은 전체 프로젝트 완료뿐 아니라 모델 응답 종료에도 발생합니다. full을 기본 사용법이나
성능 개선이 검증된 설정으로 권장하지 않습니다.

기존 매핑 대신 격리 설정을 시험할 때는 새 폴더에서 실제 모델명·숫자 포트를 지정합니다.
아래는 dry-run이며 실행하려면 `--execute`를 추가합니다.

```powershell
python bench.py --runs ./runs/isolated-01 prepare --repeats 1
python bench.py --runs ./runs/isolated-01 run --model YOUR_LOCAL_MODEL --base-url http://127.0.0.1:YOUR_PORT --timeout 300
```

이 모드는 loopback HTTP(S) 주소를 강제하고 실행별 `CLAUDE_CONFIG_DIR`를 분리합니다.
인증은 환경변수로 제공하며 `/v1` 유무는 Anthropic 호환 프록시 설정에 맞추세요.
로컬 프록시의 외부 전달이나 조직 정책까지 격리하지는 못합니다.

## 6. 결과와 캐시 해석

- `results.csv`: 실행별 상태·성공 여부·시간·토큰.
- `summary.json`, `summary.md`: 조건별 성공률·중앙 실행 시간·완료된 대응 쌍의 승패.
- 각 ID의 `execution.json`, `evaluation.json`: 실제 호출 기록과 독립 기능 검사·보호 파일 변경 감지.
- `blind-review/`: 조건명을 숨긴 코드·diff·최종 응답·평가 양식. `review-key.json`은 리뷰어에게 주지 마세요.

최종 성공은 **독립 기능 검사 통과 + 보호 파일 변경 없음 + 실제 에이전트 정상 종료**입니다.
타임아웃·CLI/API 오류는 실패이며, 평가 전 결과는 pending으로 분리합니다. 모델 미호출 성공률은
`null`이고 수동 채점만 한 결과는 모델 성능 측정에 포함하지 않습니다. 코드나 실행 기록이 바뀌면 다시 채점하세요.
정성 점수는 사람이 작성하며 `report`는 기존 리뷰 점수를 보존합니다.

CLI/API가 반환한 경우 `cache_read_input_tokens`, `cache_creation_input_tokens` 원시 값을 기록합니다.
빈 토큰·캐시 칸은 **미제공/알 수 없음**이지 0이 아닙니다. 서버가 제공하지 않은 값을 추정하지 않습니다.
고정 MD는 안정적인 입력 조건을 만드는 데 도움이 될 수 있지만, 실제 요청의 프롬프트 접두부는 CLI가 구성합니다.
백엔드·CC Switch·GLM 경로의 캐시 지원과 적중은 별도로 확인해야 합니다. Claude와 Codex 사이의 KV 캐시
공유도 보장하지 않습니다. 설치나 자체 검사로 캐시 적중·가속 효과를 검증했다고 해석하지 마세요.

성공률과 총 시간을 함께 비교하세요. 작은 문제군의 반복을 독립된 새 문제처럼 취급하지 마세요.
자동 유의성 검정·LLM 심사·거짓 완료 자동 판정은 제공하지 않습니다.

## 7. 진단과 안전 범위

### 타임아웃·승인 오류

파일이 수정되거나 수동 테스트를 통과해도 에이전트가 정상 종료했다는 뜻은 아닙니다.
새 폴더에서 baseline 한 건을 진단하세요. 두 번째 명령은 실제 모델을 호출합니다.

```powershell
python bench.py --runs ./runs/trace-01 prepare --repeats 1
python bench.py --runs ./runs/trace-01 run --id dedupe-baseline-r1 --inherit-cli-config --diagnostics --timeout 300 --execute
```

`--diagnostics`는 도구 요청·반환·최종 결과 수신과 대기 단계를 표시합니다. 요청·반환 자체는 테스트 통과의
증거가 아닙니다. `agent-output.events.jsonl`과 `agent-output.stderr.log`에는 민감한 내용이 있을 수 있습니다.
최종 결과가 없으면 `agent-output.json`은 비어 있을 수 있으며 성공 결과를 합성하지 않습니다.
`api_error`에는 최종 JSON 누락·파싱 오류도 포함될 수 있으므로 경고 한 줄만으로 원인을 단정하지 마세요.

승인 오류는 모델 연결 오류와 구분하세요. 두 조건의 동일한 `TASK.md`는 공개 테스트를 단일 명령으로 실행하고
추가 검사 스크립트·`cd`·`&&`·파이프를 피하도록 지시합니다. 허용된 검사도 거부되면 `BLOCKED`와 이유를
보고하도록 하지만 강제 준수는 보장하지 않습니다. 권한 우회나 임의 스크립트 허용으로 해결하지 마세요.

### 상위 지침·환경 문제

- `Ancestor instructions detected`: 상위 `CLAUDE.md`·`CLAUDE.local.md`·`.claude/rules`를 탐지하고 해시를 기록합니다.
  실제 실행은 기본 거부합니다. 상위 지침 없는 경로가 우선이며, 영향을 검토하고 감수할 때만 `run`에
  `--allow-ancestor-instructions`를 붙이세요.
- Claude 경로 오류: 같은 셸의 `claude --version`, JS 설치라면 `node --version`과 PATH를 확인하세요.
- `py` 오류: `python`으로 실행하면 됩니다. 기존 결과 폴더 오류는 새 `--runs` 경로로 해결하세요.
- 자체 검사만 통과하고 실제 실행이 실패하면 `execution.json`·최종 출력에서 연결·인증·권한·시간 제한을 구분하세요.

### 보안과 일반화 한계

각 workspace에서는 `solution.py`만 수정할 수 있고 `TASK.md`·공개 테스트는 보호됩니다.
하지만 이것은 **OS 보안 샌드박스가 아닙니다.** 채점기는 신뢰할 수 없는 후보 Python 코드를 실제 실행합니다.
CPU·메모리·파일시스템·네트워크 격리를 제공하지 않으며 에이전트가 형제 폴더나 공개 정답을 읽을 수도 있습니다.
적대적 코드나 출판용 평가는 별도 격리 환경이 필요합니다. 기존 설정 상속 시 개인 지침·MCP·클라우드 연결도 검토하세요.

짧은 Python 문제로 다중 파일·장기 작업 효과를 일반화할 수 없습니다. Windows 네이티브를 대상으로 하지만
실제 Windows/로컬 모델 조합의 E2E 검증을 완료했다고 주장하지 않습니다. 자체 테스트의 NOT RUN 항목과
실제 실행 로그를 구분하세요. 원본 로그·인증·환경변수·실험 출력은 검토 없이 Git이나 외부에 공유하지 마세요.

## 선택 사항: 독립 에이전트 실험

첨부 원본을 보존한 `agent.py`도 포함되어 있습니다. 위 MD 설치 방식이나 Claude 벤치마크와는
실행 경로가 다른 별도 실험이며 기본으로 실행되지 않습니다. 자동 패키지 설치·파일 접근·셸 실행과
검증되지 않은 KV 캐시 표시가 있으므로 [실행 방법과 주의사항](docs/standalone-agent.md)을 먼저 읽으세요.

## 8. 참고 아이디어와 구현 범위

| 참고 메커니즘 | 기본 minimal 방식의 범위 |
| --- | --- |
| 구조화된 지침 | 목표·제약·검증·결과 보고를 짧은 공통 MD로 안내. 스키마 강제 아님 |
| 탐색 제한 | 중복 탐색을 줄이라는 소프트 지침. 도구 호출 차단·강제 단계 엔진 아님 |
| 출력 압축·외부 상태 | 전역 도구 결과 압축 없음. 동적 작업 상태 파일 없음 |
| 고정 입력·캐시 | 고정 MD만 배포. 서버 think 설정·KV 설정·KV 포킹·CLI 간 공유 구현 없음 |

- `minimal-kit/INSTRUCTIONS.md`: 공통 지침 원본.
- `scripts/install_instructions.py`: 프로젝트별 관리 블록 미리보기·설치·제거.
- `bench.py`, `tasks.py`, `grader.py`, `reporting.py`: Claude 실행·문제·독립 채점·보고서.
- `quality-kit/`: 레거시 실험 코드와 호환 실행기. 기본 경로에 훅을 추가하지 않습니다.

아이디어 참고: https://javaexpert.tistory.com/1704
원문 코드나 성능 수치를 재현한 것은 아닙니다.
CLI·훅 규약은 [Claude Code 문서](https://code.claude.com/docs/en/cli-reference)와
[훅 문서](https://code.claude.com/docs/en/hooks)를 참고하세요.
