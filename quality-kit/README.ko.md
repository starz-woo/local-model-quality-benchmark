# 프로젝트 지침 배포와 레거시 키트 안내

기본 사용법은 `minimal-kit/INSTRUCTIONS.md`의 공통 지침을 프로젝트 `CLAUDE.md`·`AGENTS.md`에
설치하고, 평소처럼 `claude` 또는 `codex`를 실행하는 것입니다. `quality-kit/`를 복사하거나 훅을 등록할 필요는 없습니다.
품질·속도 개선은 입증하지 않았으며, 설치 성공이 모델의 지침 로딩·준수나 캐시 적중을 보장하지 않습니다.

아래 Python 명령은 이 저장소 루트에서 실행합니다. Python 3.10 이상과 표준 라이브러리만 사용합니다.
Windows 네이티브 PowerShell에서도 사용할 수 있고 WSL은 필요 없습니다. `python`이 동작하면 `py`는
없어도 됩니다. macOS/Linux에서 `python3`만 된다면 명령의 `python`을 바꿔 쓰세요.
모델 주소·인증·CC Switch 매핑은 기존 CLI 환경에서 관리합니다.

## 1. 프로젝트에 최소 지침 설치

`C:/work/my-project`를 대상 프로젝트 경로로 바꾸세요. macOS/Linux에서도 해당 환경의 경로를 사용하면 됩니다.

```powershell
# 미리보기: 파일을 쓰거나 모델을 호출하지 않음
python scripts/install_instructions.py --target "C:/work/my-project" --cli both

# 실제 적용
python scripts/install_instructions.py --target "C:/work/my-project" --cli both --apply
```

| 옵션 | 대상 파일 |
| --- | --- |
| `--cli claude` | `CLAUDE.md` |
| `--cli codex` | `AGENTS.md` |
| `--cli both` (기본값) | 두 파일 모두 |

공통 원본은 `minimal-kit/INSTRUCTIONS.md` 하나입니다. 설치기는 선택한 파일에 관리 블록을 넣고,
다시 적용하면 같은 블록을 갱신합니다. 기존 파일의 블록 밖 내용은 보존하며 같은 지침을 중복 추가하지 않습니다.
심볼릭 링크 대상이나 충돌·손상된 관리 마커가 있으면 쓰기를 거부하므로 먼저 파일을 검토하세요.

`.claude/settings.json`, 인증 파일, 모델 설정, CC Switch 설정은 변경하지 않습니다.
전역 MD·훅·자동 메모리 설정도 설치하거나 변경하지 않습니다. 동적 작업 단계·진행률·임시 상태는 MD에 기록하지 않습니다.

적용 후 **대상 프로젝트로 이동해서** 새 세션을 시작하세요. 아래는 실제 CLI 세션을 시작하는 명령입니다.

```powershell
claude
# 또는
codex
```

지침 파일을 읽는 범위·우선순위는 각 CLI의 규칙과 설정에 따릅니다. 두 CLI의 지침 원본이 같아도
도구·프롬프트 구성·모델·동작까지 같다는 뜻은 아닙니다. Codex 자동 벤치마크는 제공하지 않습니다.

### 업데이트와 제거

원본 지침이 변경되면 같은 설치 명령을 미리보기한 뒤 `--apply`로 갱신하세요.
제거도 기본은 미리보기이며 `--apply`를 붙여야 파일을 수정합니다.

```powershell
python scripts/install_instructions.py --target "C:/work/my-project" --cli both --remove
python scripts/install_instructions.py --target "C:/work/my-project" --cli both --remove --apply
```

선택한 파일의 관리 블록만 제거합니다. 기존 사용자 지침이나 별도로 등록한 훅은 제거하지 않습니다.
프로젝트의 Git 정책에 맞게 지침 변경 diff를 검토하세요.

## 2. 기본 실행기는 기존 Claude 그대로

직접 `claude`를 실행하면 충분합니다. 호환 실행기를 쓰고 싶다면 다음 명령을 사용할 수 있습니다.
아래 상대 경로는 저장소 루트 기준이며, 다른 프로젝트에서 사용하려면 실행기의 실제 경로를 지정하세요.

```powershell
# 경로·command_prefix·프로필 확인: 모델 호출 없음
python quality-kit/launch.py --check

# 기존 Claude 세션 시작: 실제 모델 호출 가능
python quality-kit/launch.py
```

기본 실행은 기존 Claude CLI로 인자를 전달할 뿐, 키트 프롬프트·훅을 주입하거나 설정을 바꾸지 않습니다.
설치된 `CLAUDE.md`는 Claude의 평소 규칙으로 읽습니다. 사용자의 기존 훅이나 자동 메모리도 이 실행기가 끄지 않습니다.
`--baseline`은 이 일반 실행의 별칭이며, **이미 설치된 MD를 끄는 옵션이 아닙니다.**
따라서 이 실행기의 기본 실행과 `--baseline`을 지침 적용 전후 A/B로 비교하지 마세요.

`--check`는 선택한 실행 경로·프로필 검사입니다. 인증·모델 연결·MD 로딩·캐시 적중을 확인하지 않습니다.
공식 native Claude와 npm `.cmd`/`.bat` 설치를 지원하고 JS 진입점은 Node가 필요합니다.
사용자 정의 배치·PowerShell 래퍼의 추가 명령은 실행하지 않습니다.

## 3. 모델 호출 전 검사와 A/B

```powershell
python scripts/run_tests.py
```

자체 검사는 모델을 호출하지 않습니다. 실제 성능 비교는 [루트 README](../README.md)의
자체 검사 → dry-run → 선택적 한 문제 A/B 순서를 따르세요.
벤치마크는 `baseline`과 `minimal`을 기본 준비하며, minimal workspace의 `CLAUDE.md`에 공통 원본을 배포합니다.
키트 복사·`--append-system-prompt` 없이 비교하고 두 조건의 훅·자동 메모리를 끕니다. `TASK.md`는 동일합니다.
이 제어는 벤치마크에만 해당하며 일반 프로젝트 설치에는 적용되지 않습니다.

`run`·`evaluate`·`report`는 Claude 전용입니다. 기존 연결을 쓰는 `--inherit-cli-config`는 개인 지침·MCP·
클라우드 매핑의 영향을 유지합니다. 실제 실행은 `--execute`로만 시작하며 상위 지침 발견 시 기본 거부합니다.
허용 여부는 dry-run을 검토한 뒤 판단하세요. `--allow-ancestor-instructions`는 격리 기능이 아니라 영향 수락입니다.

채점은 신뢰할 수 없는 후보 코드를 실행하며 OS 샌드박스가 아닙니다. 실제 Windows/로컬 모델 조합의
E2E 검증 완료나 품질 향상을 자체 테스트 결과로 대신 주장하지 않습니다.

## 4. 최소 지침이 하는 일과 하지 않는 일

| 참고 아이디어 | 최소 지침의 범위 |
| --- | --- |
| 구조화된 작업·보고 | 목표·완료 조건·제약·검증을 확인하고 변경·검증·차단 사항을 보고하도록 안내 |
| 탐색 예산 | 중복 탐색을 줄이라는 소프트 지침. 도구 호출 차단이나 강제 단계 전환 없음 |
| 출력 압축 | 전역 도구 결과를 가로채거나 압축하지 않음 |
| 외부 상태 | 동적 작업 상태 파일·장기 기억 시스템을 추가하지 않음 |
| 고정 입력 | 공통 MD를 고정 배포. CLI의 전체 시스템 프롬프트·도구 목록은 제어하지 않음 |
| 서버 최적화 | `think=false`, temperature, KV 설정·포킹·CLI 간 KV 공유를 구현하지 않음 |

고정 MD는 안정적인 입력 조건을 만들 수 있지만 실제 프롬프트 접두부는 CLI가 구성합니다.
백엔드·CC Switch·GLM 연결이 캐시를 지원하고 실제 적중하는지는 별도로 확인해야 합니다.
Claude와 Codex 사이의 캐시 공유나 자동 가속을 보장하지 않습니다. 벤치마크는 API/CLI가 반환한 경우에만
`cache_read_input_tokens`·`cache_creation_input_tokens`를 기록합니다. 빈 칸은 알 수 없음이지 0이 아닙니다.

참고 글: https://javaexpert.tistory.com/1704
원문 코드·성능 수치를 재현한 구현은 아닙니다. 최소 지침은 위 아이디어 중 자연어로 안내할 수 있는 범위만 사용합니다.

## 5. 레거시 full: 명시적으로 선택하는 실험용 경로

이전 훅·추가 프롬프트 방식은 실험 재현용으로 남아 있습니다. 기본 사용법으로 권장하지 않습니다.
실제로 더 느린 실행과 타임아웃이 관찰되었으며, 효과나 정확한 비용 차이를 확정한 수치는 없습니다.

```powershell
# 레거시 프로필 확인: 모델 호출 없음
python quality-kit/launch.py --legacy-full --check

# 레거시 훅·추가 프롬프트로 Claude 세션 시작
python quality-kit/launch.py --legacy-full
```

기존 full 실험 구성을 가진 경우에만 사용하세요. 별도 프로젝트에서 이 경로를 재현하려면 레거시 키트의
실행 경로·설정·검사 명령을 검토해야 합니다. 최소 MD 설치만으로 full 검증 게이트가 구성되지는 않습니다.

- full은 도구 사용 후 검증·탐색 카운터·Stop 테스트와 재시도 등을 추가합니다. 광범위한 훅은 지연과 중복 검사를 만들 수 있습니다.
- Stop은 프로젝트 전체 완료 때만 발생하지 않습니다. 응답 종료에도 테스트가 실행될 수 있으며 실패 재시도도 총비용에 포함됩니다.
- 기본 `test_commands`는 비어 있습니다. 별도 검사 명령을 등록하지 않으면 종료 테스트 게이트가 실행된 것으로 보지 마세요.
- 훅은 사용자 권한으로 실행합니다. 신뢰하는 검사만 등록하세요. 기존 훅 중복·조직 정책·CLI 버전에 따른 동작을 확인해야 합니다.
- PostToolUse 피드백은 이미 수행한 편집을 취소하지 않으며 재시도 상한에 도달하면 실패 상태로 종료할 수 있습니다. 릴리스 차단은 CI에서 별도로 하세요.
- `compact_run.py`는 명시적으로 감싼 명령의 출력만 축약합니다. 전체 도구 결과 압축 기능이 아닙니다. 원본 로그에는 비밀이 있을 수 있습니다.

벤치마크에서 full을 준비하려면 새 폴더와 조건을 명시하세요. 아래는 모델 호출 없는 준비 명령입니다.

```powershell
python bench.py --runs ./runs/legacy-01 prepare --conditions baseline full --repeats 1
python bench.py --runs ./runs/three-01 prepare --conditions baseline minimal full --repeats 1
```

기존 full 결과의 보고서는 계속 생성할 수 있습니다. minimal과 full은 서로 다른 실험 조건이며,
지침이 바뀐 과거 실행을 같은 프롬프트의 대응 쌍으로 섞어 해석하지 마세요.

레거시 규약: https://code.claude.com/docs/en/hooks
설치·실행 진단과 안전 범위는 [루트 README](../README.md)를 참고하세요.
