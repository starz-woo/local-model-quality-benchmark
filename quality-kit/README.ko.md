# Claude Code + 로컬 모델 품질 개선 키트

참고 글: https://javaexpert.tistory.com/1704
공식 규약: https://code.claude.com/docs/en/hooks

이 패키지는 글의 아이디어를 Claude Code 공개 CLI/훅으로 적용한 별도 구현입니다.
원문 프로젝트 코드를 복사하거나 원문의 수치를 재현한 것은 아닙니다.
Windows 네이티브/ macOS / Linux, Python 3.10 이상과 기존에 로컬 모델에 연결된 Claude Code가 필요합니다.
추가 Python 패키지나 jq는 필요 없습니다. Windows는 native claude.exe와 PowerShell을 사용합니다.
WSL/Bash는 키트 실행의 필수 조건이 아닙니다. npm .cmd/.bat Claude 래퍼 대신 native 설치를 사용하세요.
Windows에서는 아래 python3 명령 대신 py -3을 사용하면 됩니다.
macOS 자체 검사는 수행했지만 실제 Windows 모델 E2E는 아직 검증하지 않았습니다.
모델 주소·인증·모델 이름은 기존 Claude Code 실행 환경을 그대로 사용합니다.

## 가장 짧은 사용법

1. ZIP을 풀고 local-quality-kit 폴더를 프로젝트 루트에 둡니다.
2. 프로젝트 루트에서 실행합니다.

```bash
python3 local-quality-kit/launch.py --check
python3 local-quality-kit/launch.py
```

기존 .claude/settings.json, CLAUDE.md, 모델 설정은 수정하지 않습니다.
전용 실행기를 사용한 세션에만 이 키트의 설정과 고정 지침이 추가됩니다.
실행 시 OS에 맞는 임시 훅 설정을 생성합니다. Windows는 PowerShell 명령을 사용하므로
settings.json 템플릿을 Windows 프로젝트에 그대로 복사하지 말고 launch.py로 시작하세요.
기존 설정의 훅도 남아 있으므로 앞서 만든 verify/gate를 동시에 사용하면 중복 검사가
발생할 수 있습니다. 이 키트를 비교 시험할 때는 기존 훅과의 중복부터 확인하세요.
훅 스크립트는 사용자 권한으로 실행되며 Claude의 개별 Bash 승인과 별개입니다.
검사 명령은 신뢰하는 프로젝트에서만 등록하세요. 권한 우회 플래그는 사용하지 않습니다.
키트 코드를 사용할 프로젝트의 Git 정책에 맞게 개인 폴더 제외 또는 별도 브랜치에서 관리하세요.

## 전체 테스트 게이트 켜기

프로젝트별 테스트 명령을 모르므로 기본 test_commands는 비어 있습니다.
이 상태에서는 종료 시 '테스트 게이트 미실행' 안내가 나오며 통과로 간주하지 않습니다.
실제로 프로젝트에서 쓰는 명령 하나를 등록하세요. 아래 예시를 전부 실행하지 마세요.

```bash
# npm 프로젝트: scripts.test가 일회성 실행인지 확인
python3 local-quality-kit/configure.py --test npm test

# Python unittest 프로젝트 예시
python3 local-quality-kit/configure.py --test python3 -m unittest discover -s tests

# 별도 테스트 래퍼가 있는 프로젝트 예시
python3 local-quality-kit/configure.py --test ./scripts/run_tests.sh
```

명령은 셸 문자열이 아니라 인자 배열로 저장됩니다. &&, |, 리다이렉션 문법을 넣지 마세요.
복합 명령은 프로젝트의 검토된 테스트 스크립트 하나로 묶어 등록하세요.
watch 모드나 입력을 기다리는 명령은 사용하지 마세요.
config.json은 키트 전체에 적용되므로 프로젝트마다 별도 키트 사본을 사용하세요.

## 추가 린터 연결

config.json의 verify_by_suffix에 필요한 명령만 넣으세요. 도구는 사전 설치해야 합니다.
키트가 자동으로 npx/pip 다운로드를 하지 않습니다.

```json
{
  ".py": [["ruff", "check", "{file}"]],
  ".ts": [["npx", "--no-install", "eslint", "{file}"]],
  ".tsx": [["npx", "--no-install", "eslint", "{file}"]]
}
```

이는 verify_by_suffix의 값 예시입니다. config.json 전체를 위 내용으로 덮어쓰지 마세요.
JS, JSX 등은 필요한 확장자를 별도로 등록하세요.
기본 검사는 Python 문법, JSON 파싱, Bash 문법이며 ESLint/타입 검사를 대신하지 않습니다.
프로젝트 전체 타입 검사는 test_commands에 별도 인자 배열로 추가할 수 있습니다.
각 기본 검사 제한은 20초, 각 테스트 명령은 90초입니다.
추가 검사나 테스트가 많아지면 settings.json의 전체 훅 timeout도 함께 조절하세요.

## 적용한 아이디어와 범위

- 구조화 프롬프트: 목표/완료 조건/제약을 먼저 확인하고 Changed/Verified/Blocked로 보고.
  자연어 지침이며 JSON 스키마 강제 기능은 아닙니다.
- 로그 압축: compact_run.py를 사용한 명령만 앞/뒤 출력으로 축약하고 전체 로그를 별도 저장.
  Claude의 기존 Read/Bash 출력 전체를 가로채거나 교체하지는 않습니다.
- 단계 관리: 도구 호출 예산에 도달하면 중복 탐색을 멈추라는 추가 컨텍스트 제공.
  호출 수는 탐색 전용이 아닌 전체 도구 기준입니다. 도구를 차단하지 않습니다.
- 외부 상태: 짧은 작업 상태 파일 사용 지침 + 훅 카운터의 세션별 디스크 저장.
  사용자 선호 장기 기억/자동 요약 시스템은 아닙니다.
- 쓰기 검증: Write 이벤트의 요청 UTF-8 내용과 디스크 바이트 비교.
  Edit는 파일 존재/문법만 확인하므로 변경 diff는 별도로 확인해야 합니다.
  Bash를 통한 파일 변경은 자동 내용 비교를 하지 않습니다.
- 고정 지침: 실행 시 고정 프롬프트를 추가하며 실행 도중 시스템 프롬프트/툴셋을 바꾸지 않음.
  실제 서버 KV 캐시 사용이나 가속 효과를 보장하지는 않습니다.
- 최종 검증: 변경 가능성이 있는 도구 사용 후, 종료 시 설정한 테스트를 실행.
  실패하면 수정 요청으로 종료를 막되 상한 초과 시 FAILED 안내 후 종료 허용.

think=false, temperature, KV cache forking, 지연 툴 로딩, 병렬 부팅은 구현하지 않았습니다.
Claude Code의 .claude 설정만으로 모든 로컬 추론 서버의 이런 기능을 제어할 수 없고,
도구를 동적으로 제거하면 코딩 작업의 검증과 캐시 재사용을 해칠 수 있기 때문입니다.
'비용 0'은 이 키트의 보장이 아닙니다. 로컬 연산/전력/장비 비용은 존재합니다.

## 로그 압축 도구 직접 사용

프로젝트 루트에서:

```bash
python3 local-quality-kit/compact_run.py -- npm test
```

기본 120초 제한, 실제 명령 종료 코드 보존, 전체 로그 위치 출력.
전체 로그는 TMPDIR의 개인 권한 파일에 저장됩니다. 로그에 비밀이 포함될 수 있으니
공유하지 말고 필요가 끝나면 표시된 파일을 직접 삭제하세요. 대용량 로그는 디스크를
소모할 수 있습니다. 중간 부분에 필요한 오류가 있으면 원문 로그를 추가로 확인하세요.
이 도구 사용은 모델에 대한 지침이며 모든 명령에서 강제되지는 않습니다.

## 적용 전/후 비교

```bash
# 이 키트만 추가하지 않는 기준 실행 (기존 Claude 설정은 유지됨)
python3 local-quality-kit/launch.py --baseline

# 적용 실행
python3 local-quality-kit/launch.py
```

동일 모델/프롬프트/시작 코드/예산의 새 세션에서 반복 비교하세요.
baseline은 전역/프로젝트 기존 훅까지 끄는 옵션이 아닙니다.
최종 평가는 키트와 독립적인 테스트로 수행하고, 성공률과 총 시간을 비교하세요.
이 키트는 현재 설치된 로컬 모델로 A/B 성능 측정까지 수행한 결과물이 아닙니다.

## 자체 코드 테스트

```bash
cd local-quality-kit
python3 -m unittest -v test_kit.py
```

이는 키트의 단위/서브프로세스 테스트이며 실제 Claude 모델의 품질 평가가 아닙니다.

## 한계와 복구

- 새 세션에서 /hooks로 등록 확인. --bare, --safe-mode 또는 조직 정책으로 훅이 꺼져 있으면 작동하지 않을 수 있음.
- 검증 오류는 PostToolUse additionalContext로 피드백하며 이미 수행한 편집을 취소하지 않음.
- 코드 편집 외의 Bash 실행도 보수적으로 변경 가능성으로 간주하므로 불필요한 테스트가 실행될 수 있음.
- Stop은 '전체 프로젝트 완료'만이 아니라 모델 응답 종료 때도 발생함.
- retry exhaustion은 실패 상태 그대로 종료 허용. 엄격한 릴리스 차단은 CI에서 별도로 수행.
- 기존 훅/조직 설정과의 충돌, 실제 모델의 지침 준수는 각 환경에서 확인해야 함.
- 임시 세션 상태는 TMPDIR/local-quality-kit에 저장. 원문 세션 ID는 해시 처리.
- 키트 없이 평소처럼 claude를 실행하면 이 키트는 추가되지 않음. 프로젝트 설정 복구는 필요 없음.
- 키트 폴더는 모델이 수정할 수 있는 위치일 수 있으므로 보안 경계가 아님.

구현 코드는 원문 글의 성능 수치를 보증하지 않으며, Claude Code 내부 엔진 수정도 하지 않습니다.
