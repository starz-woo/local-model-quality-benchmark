# Local Model Quality Kit + A/B Benchmark

이미 Claude Code에 연결한 로컬 모델을 그대로 사용하면서 **품질 개선 키트 적용 전/후**를 비교합니다.
별도 에이전트를 만드는 것이 아니라 기존 `claude -p`를 실행하고, 결과 코드를 외부 테스트로 채점합니다.
Python 표준 라이브러리만 사용합니다.

> 자체 테스트 통과는 실행기·키트의 정상 동작을 뜻합니다. 모델 품질 향상을 입증하는 결과가 아닙니다.
> 이 저장소는 짧은 Python 문제로 구성한 파일럿이며, 실제 모델의 개선 수치는 아직 측정하지 않았습니다.

## 시작 순서

1. [실행 환경 확인](#1-실행-환경-확인)
2. [빠른 테스트: 모델 호출 없이 확인](#2-빠른-테스트-모델-호출-없이-확인)
3. [빠른 A/B: 한 문제만 비교](#3-빠른-ab-한-문제만-비교)
4. [전체 벤치마크](#4-전체-벤치마크)
5. [결과 파일과 해석](#5-결과-파일과-해석)
6. [실행 모드와 비교 조건](#6-실행-모드와-비교-조건)
7. [내 프로젝트에 키트만 적용](#7-내-프로젝트에-키트만-적용)
8. [문제 해결](#8-문제-해결)
9. [구성 파일과 검증 범위](#9-구성-파일과-검증-범위)

## 1. 실행 환경 확인

**아래 명령은 모두 저장소 루트에서 실행합니다.** Windows PowerShell에서도 복사할 수 있도록
명령은 한 줄씩 작성했습니다.

```powershell
python --version
```

- Python 3.10 이상. `pip install`이나 추가 Python 패키지는 필요 없습니다.
- Windows 네이티브(PowerShell), macOS, Linux를 대상으로 합니다. WSL은 필수가 아닙니다.
- 이 문서는 `python` 기준입니다. macOS/Linux에서 `python3`만 된다면 `python`을 `python3`로 바꾸세요.
- **`py`는 필수가 아닙니다.** `python`이 동작하면 Windows Python Launcher인 `py`가 없어도 됩니다.
- **자체 검사·벤치마크 dry-run:** Claude, Node, 모델 서버가 없어도 실행할 수 있습니다.
- **실제 A/B:** 평소 Claude Code에서 로컬 모델 호출이 되는 환경이 필요합니다.
  Windows는 native `claude.exe` 및 공식 npm 설치의 `.cmd`/`.bat`를 지원합니다.
  JS 진입점은 `node.exe`가 필요하며, EXE 진입점은 직접 실행합니다.

기존 연결 설정을 바꾸거나 모델 서버를 새로 설치하는 도구가 아닙니다.
Claude Code에는 Anthropic 호환 API 또는 변환 프록시가 필요하며,
OpenAI 호환 `/v1/chat/completions` 주소만으로 직접 연결되지는 않습니다.

## 2. 빠른 테스트: 모델 호출 없이 확인

### A. 실행기와 키트 자체 검사

```powershell
python scripts/run_tests.py
```

벤치마크·런타임 검사와 키트 검사가 차례로 실행됩니다. 두 검사 묶음 모두 `OK`면 통과입니다.
모델 호출, 패키지 설치, 모델 다운로드는 하지 않습니다.
**여기까지만 해도 설치한 코드의 자체 검증은 끝입니다.**

### B. Claude 설치 경로 확인 — 실제 A/B를 할 경우에만

```powershell
python quality-kit/launch.py --check
```

모델은 호출하지 않습니다. 출력의 `claude`와 `command_prefix`로 실제 선택한 실행 경로를 확인하세요.
공식 npm 전역 설치와 `node_modules/.bin`을 지원하며, PATH에서 먼저 찾은 Claude를 사용합니다.

- JS 설치 예: `command_prefix`가 Node 실행 파일 + CLI 스크립트.
- native 설치 예: `command_prefix`가 Claude 실행 파일.
- 이 명령은 **설치 경로 검사**이지 모델 연결·인증 성공 검사가 아닙니다.

## 3. 빠른 A/B: 한 문제만 비교

전체 배치를 실행하기 전에 **중복 제거 문제 하나를 baseline/full 각각 실행**해 흐름을 확인합니다.
`baseline`은 키트 미적용, `full`은 고정 지침 + 키트 훅 적용입니다.

### A. 새 작업 폴더 준비 — 모델 호출 없음

```powershell
python bench.py --runs ./runs/quick-01 prepare --repeats 1
```

모든 문제의 작업 폴더를 만들지만, 아래에서는 `--id`로 중복 제거 문제만 선택합니다.
기존 결과는 덮어쓰지 않습니다. 재시도할 때는 `quick-02`처럼 **새 경로**를 쓰고 이후 명령도 바꾸세요.

### B. 실행할 명령 확인 — 모델 호출 없음

```powershell
python bench.py --runs ./runs/quick-01 run --id dedupe-baseline-r1 --inherit-cli-config
python bench.py --runs ./runs/quick-01 run --id dedupe-full-r1 --inherit-cli-config
```

`dry_run: true`, `model_connection: inherited`, 실행 명령과 작업 위치가 출력되면 정상입니다.
`--inherit-cli-config`는 기존 모델 매핑·인증·환경변수·사용자 설정을 유지합니다.

### C. 실제 실행 — 여기서부터 모델 호출

> **실행 전 확인:** 기존 Claude 설정이 클라우드 모델이면 그대로 클라우드를 호출할 수 있습니다.
> 로컬 모델에 연결된 환경인지 확인한 뒤에만 아래 `--execute` 명령을 실행하세요.

```powershell
python bench.py --runs ./runs/quick-01 run --id dedupe-baseline-r1 --inherit-cli-config --execute
python bench.py --runs ./runs/quick-01 run --id dedupe-full-r1 --inherit-cli-config --execute
```

각각 새 작업 폴더·새 세션에서 실행합니다. 기본 시간 제한은 실행별 300초입니다.
상위 지침 탐지로 중단되면 [문제 해결](#8-문제-해결)을 확인하세요.
이미 시작한 ID는 같은 폴더에서 다시 실행하지 않습니다.

### D. 두 결과 채점 후 보고서 생성 — 모델 호출 없음

```powershell
python bench.py --runs ./runs/quick-01 evaluate --id dedupe-baseline-r1
python bench.py --runs ./runs/quick-01 evaluate --id dedupe-full-r1
python bench.py --runs ./runs/quick-01 report
```

`runs/quick-01/summary.md`와 `results.csv`를 확인하세요.
나머지 문제는 실행하지 않았으므로 미실행으로 남는 것이 정상입니다.
**이 빠른 테스트는 흐름 확인용이며 한 문제의 결과만으로 품질 향상을 결론 내리지 마세요.**

## 4. 전체 벤치마크

빠른 A/B가 정상 동작하면 새 폴더에서 전체 문제를 반복 실행합니다.
문제는 중복 제거, 페이지네이션, 금액 반올림, 예외 재시도, 구간 병합입니다.

```powershell
# 준비 → dry-run: 모델 호출 없음
python bench.py --runs ./runs/pilot-01 prepare --repeats 3
python bench.py --runs ./runs/pilot-01 run --inherit-cli-config
```

기존 로컬 모델 매핑을 확인한 뒤 실제 실행합니다.

```powershell
# 실제 모델 호출: manifest 순서대로 전체 배치를 순차 실행
python bench.py --runs ./runs/pilot-01 run --inherit-cli-config --execute

# 독립 채점 → 보고서: 모델 호출 없음
python bench.py --runs ./runs/pilot-01 evaluate
python bench.py --runs ./runs/pilot-01 report
```

- 실행 순서는 고정 seed로 섞습니다. 동일 문제·반복의 시작 코드와 요청은 두 조건에서 같습니다.
- 재실험은 새 `--runs` 경로에서 시작하세요. 이미 시작한 작업 폴더는 재사용하지 않습니다.
- 중간에 멈췄다면 `manifest.json`과 각 ID의 실행 기록을 확인하고, **아직 시작하지 않은 ID**를 `--id`로 실행하세요.
- 모델 파일·양자화·서버 버전·생성 옵션은 `run`의 `--model-notes "환경 설명"`으로 기록할 수 있습니다.
- 같은 머신에서 병렬 추론하지 말고 워밍업·온도·컨텍스트·양자화·시간 예산을 고정하세요.

## 5. 결과 파일과 해석

`--runs`로 지정한 폴더에 생성됩니다.

- `results.csv`: 실행별 상태·성공 여부·시간·토큰.
- `summary.json`, `summary.md`: 조건별 성공률·중앙 실행 시간·대응 승패.
- 각 ID의 `execution.json`: 실제 호출·종료 상태·시간·서버가 제공한 usage.
- 각 ID의 `evaluation.json`: 독립 기능 검사와 보호 파일 변경 감지.
- `blind-review/`: 조건명을 숨긴 코드·diff·최종 응답·평가 양식.
- `review-key.json`: 블라인드 ID와 원래 조건의 대응표. **리뷰어에게 전달하지 마세요.**

**최종 성공 = 독립 기능 검사 통과 + 보호 파일 변경 없음 + 실제 에이전트 정상 종료.**
CLI/API 오류와 타임아웃은 실패이며, 평가 전 실행은 pending으로 분리합니다.
모델 미호출 결과는 성공률 `null`이고, 수동 평가만 수행한 결과는 모델 성능 측정에 포함하지 않습니다.
서버/CLI가 제공하지 않은 토큰 수는 추정하지 않습니다.

정성 평가는 `blind-review/rubric.md`와 `scores.template.csv`로 사람이 작성합니다.
요구사항 충족·변경 범위·유지보수성·보고 정확성을 따로 보며 점수를 자동 생성하지 않습니다.
반복 `report`는 기존 점수를 보존하면서 새 블라인드 ID를 추가합니다.
테스트 변경 금지 과제이므로 테스트 작성 능력은 N/A입니다.

채점은 workspace·실행 기록 해시에 묶입니다. 이후 코드나 실행 기록이 바뀌면 다시 `evaluate`하세요.
`SkipTest`는 통과로 인정하지 않으며, 허용 파일 외의 추가·삭제·변경도 감지합니다. 캐시 폴더는 제외합니다.

성공률과 시간 증가를 함께 보세요. full의 재시도·훅 시간도 비용에 포함됩니다.
대응 승패는 양쪽 실행·평가가 완료된 쌍만 계산합니다. 작은 문제군의 반복을 독립된 새 문제처럼
취급하지 마세요. 자동 신뢰구간·유의성 주장·LLM 심사·거짓 완료 자동 판정·ablation은 미구현입니다.

## 6. 실행 모드와 비교 조건

### 기존 매핑 유지 — 위 가이드의 기본 모드

`--inherit-cli-config`는 기존 Claude 설정·인증·환경변수·MCP 연결을 유지합니다.
필요하면 `--model`로 기존 별칭을 명시할 수 있습니다. 완전 격리 비교는 아닙니다.

- benchmark baseline은 `disableAllHooks: true`로 **사용자 훅도 끕니다**.
- full은 훅을 명시적으로 켜고 고정 지침·키트 훅·공개 테스트 명령을 추가합니다.
- 조직 관리 정책은 우회하지 않습니다. 기존 훅 중복과 정책에 의한 비활성화를 확인하세요.
- 기존 매핑이 클라우드라면 그대로 호출할 수 있습니다. 로컬 연결 여부는 사용자가 확인해야 합니다.

### 모델·로컬 주소 명시 — 설정 격리 모드

기존 CLI 매핑에 의존하지 않고 비교할 때만 사용하세요. 아래 모델명·포트는 자리표시자이므로
**실제 모델명과 숫자 포트**로 바꾸세요. 인증은 환경변수로 제공합니다.

```powershell
# 별도 새 폴더 준비
python bench.py --runs ./runs/isolated-01 prepare --repeats 1

# 모델 호출 없는 dry-run; 실제 실행에는 같은 명령 끝에 --execute 추가
python bench.py --runs ./runs/isolated-01 run --model YOUR_LOCAL_MODEL --base-url http://127.0.0.1:YOUR_PORT --timeout 300
```

이 모드만 loopback HTTP(S) 주소를 강제합니다. `/v1` 유무는 Anthropic 호환 프록시 설정에 맞추세요.
로컬 프록시가 다시 외부로 전달하는지는 실행기가 판별할 수 없습니다.
실행별 `CLAUDE_CONFIG_DIR`를 분리하고 사용자/프로젝트 설정 및 사용자 MCP 로딩을 제외합니다.
이는 OS 샌드박스가 아니며 조직 정책·상위 지침을 완전히 격리하지 않습니다.

두 모드 모두 상위 `CLAUDE.md`·`CLAUDE.local.md`·`.claude/rules`를 탐지해 해시를 기록합니다.
발견하면 실제 실행을 기본 거부합니다. 두 조건 모두 폐기 가능한 workspace에서 `acceptEdits`를 쓰고,
Python unittest 실행을 제한적으로 허용합니다. 전체 권한 우회 플래그는 쓰지 않습니다.
그 외 명령은 거부될 수 있으므로 로그를 확인하세요. 실행 도중 시스템 프롬프트·도구 목록은 바꾸지 않습니다.

## 7. 내 프로젝트에 키트만 적용

벤치마크 없이 사용할 경우 [키트 사용 가이드](quality-kit/README.ko.md)를 따르세요.
대상 프로젝트 루트에 `quality-kit/` 사본을 두고 실행합니다.

```powershell
python quality-kit/launch.py --check
python quality-kit/launch.py
```

두 번째 명령은 실제 Claude 세션을 시작합니다. 기존 `.claude/settings.json`, `CLAUDE.md`, 모델 설정을
덮어쓰지 않고 이 세션에만 키트를 추가합니다. 기본 `test_commands`는 비어 있으므로,
프로젝트 테스트를 별도로 등록해야 종료 테스트 게이트가 동작합니다.
벤치마크의 full 작업에는 공개 테스트 명령이 자동 등록됩니다.

## 8. 문제 해결

- **`py`를 찾을 수 없음:** `python`이 동작하면 그대로 쓰세요. `py`는 별도 Windows Launcher이며 필수가 아닙니다.
- **`python`을 찾을 수 없음:** Python 설치/PATH를 확인하세요. macOS/Linux는 `python3`도 확인하세요.
- **`--check`에서 Claude를 찾을 수 없음:** 같은 셸에서 `claude --version`을 확인하고 PATH를 점검하세요.
- **npm 설치인데 Node.js 오류:** JS CLI 버전은 `node.exe`가 필요합니다. `node --version`과 Node PATH를 확인하세요.
- **과거 `.cmd/.bat shims are not supported` 오류:** 수정 전 코드입니다. 최신 코드를 받은 뒤 자체 검사를 다시 실행하세요.
- **사용자 정의 래퍼/PowerShell 별칭:** 래퍼 내부의 환경변수 설정·추가 명령은 실행하지 않습니다.
  공식 npm/native CLI를 사용하고 모델 매핑은 기존 Claude 설정이나 부모 셸 환경변수로 제공하세요.
- **`Ancestor instructions detected`:** 상위 지침 없는 경로에 저장소/작업 폴더를 두는 것이 우선입니다.
  dry-run의 `ancestor_instructions`를 검토하고 영향을 감수할 때만 `run`에 `--allow-ancestor-instructions`를 추가하세요.
- **이미 준비/실행된 폴더 오류:** 기존 결과를 지우기보다 새 `--runs` 경로에서 시작하세요.
- **자체 검사는 OK인데 실제 실행 실패:** 자체 검사는 모델 연결을 검사하지 않습니다.
  각 ID의 `agent-output.json`과 `execution.json`에서 인증·연결·권한·시간 초과를 확인하세요.
  원본 출력에 비밀이 있을 수 있으니 공유 전 가리세요.

## 9. 구성 파일과 검증 범위

- `quality-kit/`: 고정 지침, 검증 훅, 로그 압축 도구, 전용 실행기.
- `bench.py`: 작업 준비 → Claude 실행 → 독립 채점 → 보고서.
- `tasks.py`: 한국어 문제·시작 코드·공개 테스트·채점기 검증용 정답.
- `grader.py`: workspace 밖의 추가 기능/회귀 검사.
- `reporting.py`: 집계와 블라인드 리뷰 묶음.

각 작업은 `workspace/solution.py`만 수정할 수 있으며 `TASK.md`, `tests/test_public.py`는 보호됩니다.
full의 `kit/`과 설정·메타데이터는 workspace 밖에 둡니다. 평가용 추가 검사·정답은 workspace로 복사하지 않습니다.

**보안 샌드박스가 아닙니다.** Bash 권한이 있는 에이전트는 형제 폴더나 공개 정답을 읽을 수 있습니다.
채점도 후보 Python 코드를 실제 실행하며, CPU·메모리·디스크·네트워크 보안 격리를 제공하지 않습니다.
적대적 코드·출판용 평가에는 별도 컨테이너/파일시스템·네트워크 격리가 필요합니다.
공개 정답에 따른 학습 오염 가능성도 있습니다.

짧은 Python 문제만으로 다중 파일·긴 로그·장기 상태 관리 효과를 일반화할 수 없습니다.
전체 도구 transcript를 수집하지 않으므로 일부 검증 주장은 근거 부족으로 남을 수 있습니다.
`think=false`, temperature 제어, KV 캐시 포킹, 추론 서버 최적화는 구현하거나 검증하지 않았습니다.

Windows는 msvcrt 잠금·taskkill 프로세스 트리 종료·PowerShell 훅을 사용합니다.
Bash가 없는 환경의 `.sh` 문법 검사는 NOT RUN입니다.
macOS 자체 검사와 사용자의 Windows 자체 검사 통과 보고가 있으며,
개발 환경에서의 실제 Windows/로컬 모델 E2E 검증은 아직 없습니다.
`examples/github-actions-test.yml`은 CI 템플릿이지 실행된 CI 성공 기록이 아닙니다.
Claude Code 자체의 셸 지원은 [공식 설치 문서](https://code.claude.com/docs/en/setup)를 확인하세요.

원본 출력·토큰·환경변수·인증 파일은 Git에 올리지 마세요. 기본 `.gitignore`로 실험 출력을 제외합니다.

## 참고

- 아이디어 소개: https://javaexpert.tistory.com/1704
- Claude Code 훅 규약: https://code.claude.com/docs/en/hooks
- CLI 규약: https://code.claude.com/docs/en/cli-reference
