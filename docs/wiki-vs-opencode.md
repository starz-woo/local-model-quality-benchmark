# Windows: 실제 Wiki Agent vs 실제 OpenCode

모델 벤치마크는 **사용자가 Windows에서 실행**합니다. 이 PR에서는 모델 호출·로컬 추론·OpenCode 설치·성능 측정을 하지 않았습니다. 기본 명령은 외부 프로세스도 실행하지 않는 offline preflight입니다.

## 빠른 실행 (PowerShell, Python 3.10+)

ZIP을 새 폴더에 풀거나 PR 브랜치를 checkout한 뒤 그 폴더에서:

```powershell
python wiki_benchmark.py
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-wiki.txt
```

OpenCode는 사용자가 별도로 설치해야 합니다. **이 작은 runner의 지원 계약은 OpenCode 1.2.27**입니다. 기존 전역 설치를 바꾸지 않으려면 별도 prefix에 명시적으로 설치하세요 (Node.js/npm 필요):

```powershell
npm install --prefix .opencode-cli opencode-ai@1.2.27
```

최신 OpenCode v2는 config 스키마가 다르므로 버전이 다르면 모델 호출 전에 중단합니다. 다른 설치가 1.2.27이면 `--opencode opencode`를 사용할 수 있습니다. npm `.cmd`를 CMD 문자열로 실행하지 않고 공식 package.json의 Node/native entry point로 해석합니다.

키는 기존 환경변수에서 읽거나 PowerShell masked prompt로 설정하세요. 키를 명령행 인자나 코드에 넣지 마세요:

```powershell
$secret = Read-Host 'GLM API key' -AsSecureString
$env:GLM_API_KEY = [System.Net.NetworkCredential]::new('', $secret).Password
$env:WIKI_BENCH_MODEL = Read-Host 'Exact GLM API model ID'
$env:WIKI_BENCH_BASE_URL = Read-Host 'OpenAI-compatible base URL'
.venv\Scripts\python.exe wiki_benchmark.py --opencode .opencode-cli\node_modules\.bin\opencode.cmd
.venv\Scripts\python.exe wiki_benchmark.py --execute --opencode .opencode-cli\node_modules\.bin\opencode.cmd --output "$env:TEMP\wiki-run-01"
```

ID/endpoint에 기본 alias나 localhost를 가정하지 않습니다. 키 이름은 `--key-env MY_KEY`, ID/endpoint는 `--model EXACT_ID --base-url https://YOUR_ENDPOINT/v1`로도 지정 가능합니다. API가 실제로 지원하는 정확한 값과 endpoint를 사용하세요. GLM Coding Plan/API endpoint는 서로 같다고 가정하지 않습니다.

결과: 지정한 새 폴더의 `results.csv`, `report.md`, `protocol.json`. 기존 폴더를 덮어쓰지 않습니다. 재실행은 `wiki-run-02`처럼 새 경로를 지정하세요. 종료 코드 1은 실패/timeout/미통과가 포함되었다는 뜻입니다. 기본 3개 task, 2회 반복, 두 agent로 실행합니다. 예: `--tasks dedupe --repeats 2 --timeout 120 --max-steps 10`.

## 실제로 무엇을 비교하나요?

- 사용자 agent는 **setup_agent.py의 STRUCTURE에서 생성한 `agent.engine.AgentEngine`**입니다. root `agent.py`나 별도 흉내 loop를 사용하지 않습니다. 실제 `run_turn`, streaming client, XML parser, read/edit/bash/grep/glob/lint/fetch/search tool을 실행합니다.
- OpenCode는 실제 `opencode run --format json --model benchmark/EXACT_ID --agent build PROMPT`입니다. `benchmark`는 runner가 정의한 custom provider ID일 뿐 모델 alias가 아닙니다. 두 agent 모두 사용자가 준 같은 endpoint와 model ID를 요청합니다.
- 기존 `tasks.py` 중 dedupe/pagination/money 기본 선택, retry/intervals 추가 선택 가능. 동일 starter/public tests/request와 wall timeout/step 설정을 줍니다. 양수 짝수 반복을 강제하고 task마다 AB/BA 순서를 반복합니다.
- run마다 새 workspace/설정/세션/위키를 사용합니다. 두 조건에 같은 `.agent_wiki/index.md` 빈 초기 지식을 제공하고 `.md` 메모만 허용합니다. task 간 Wiki 누적 학습 성능을 측정하지 않습니다.
- `grader.py`는 workspace 밖에서 실행하고, 별도 임시 폴더의 solution snapshot을 검사합니다. 공개 테스트 변경/허용되지 않은 새 파일은 integrity failure입니다. agent 실행 시간은 실패·timeout도 합산하며 grading 시간은 포함하지 않습니다. 실패는 분모에서 빼지 않습니다.
- tokens/cost/cache hit은 일관된 계측을 하지 않으므로 **unknown**입니다. 0으로 추정하지 않습니다. raw output과 예외 메시지는 키 유출을 피하려고 runner 보고서/콘솔에 기록하지 않습니다. OpenCode 자체가 isolated state 아래에 생성하는 세션/로그는 민감할 수 있으므로 결과 폴더 전체를 공개하지 마세요.

## 원본 보존 및 최소 startup 수리

`setup_agent.py`는 **변경하지 않았습니다**. `wiki_adapter.py`는 AST literal로 STRUCTURE만 읽습니다. import 시 사용자 소스를 실행하거나 generator main을 호출하지 않습니다. `--execute` worker가 별도 generated 폴더에 만든 파일에만 다음 세 수리를 적용합니다:

1. engine edit regex의 깨진 single-quote Python 문자열을 triple-quoted raw 문자열로 수리.
2. `ToolRegistry.register(name, func)`에 기존 호출 방식 + decorator 방식 `@register(name)`을 지원하도록 수리.
3. engine에서 file_tools/search_tools/sys_tools를 import하여 실제 tool registry를 채움.

headless adapter는 UI edit 승인만 자동 허용하고 markdown-save 입력은 빈 문자열로 처리합니다. 원래 prompt/parser/위키/편집/tool 구현은 유지합니다. client의 model/base URL/API key만 runtime으로 교체하고 HTTP timeout=60s/retries=0을 적용합니다. 원본 LLM client의 temperature=0, max_tokens=2048, stop tags, `cache_prompt=true`, `reasoning_effort=high`, `clear_thinking=true`는 유지합니다. provider가 이 extra_body나 stop를 거절하면 실패로 남으며 조용히 다른 모델/옵션으로 대체하지 않습니다.

## 권한·공정성·보안 한계

**격리된 작업 폴더이지 sandbox가 아닙니다.** `--execute`는 Wiki edit 자동 승인과 원본 shell/network tool 실행, OpenCode all-allow 권한을 명시적으로 허용합니다. 절대 경로·shell·network가 호스트에 접근할 수 있습니다. 숨은 테스트는 작업 폴더에 없을 뿐 악의적인 agent로부터 비밀인 것은 아닙니다. **중요 파일/자격증명이 없는 disposable Windows 계정 또는 VM에서 실행**하세요.

OpenCode config는 merge되므로 custom config 경로 하나만 설정하지 않습니다. 매 run HOME/USERPROFILE/XDG roots/APPDATA/LOCALAPPDATA/OPENCODE_CONFIG_DIR를 새 경로로 바꾸고 상속 OPENCODE_*를 제거하며 inline config를 넣습니다. 전역 config/auth를 덮어쓰지 않습니다. output은 프로젝트/git checkout 밖(`$env:TEMP\wiki-run-01`)을 권장합니다. 상위 프로젝트 config/instructions와 관리자 managed config는 영향을 줄 수 있습니다. 관리자 정책을 우회하지 않습니다. 통제된 Windows 계정에서 정책/부모 설정이 없는지 확인하세요.

같은 모델명·task·wall budget을 요청해도 **정확한 parity를 주장하지 않습니다**. Wiki는 XML text tools와 원본 high-thinking extra_body, OpenCode는 자체 build prompt/native tool calls/provider thinking defaults/compaction/SDK를 사용합니다. step cap 의미와 추가 종료 turn, 출력 token 제한, retry, shell 선택도 다릅니다. Windows Wiki `<bash>`는 Python shell=True의 cmd.exe이며 OpenCode는 자체 shell 선택입니다. OpenCode 설치/첫 provider SDK 준비 비용은 사용자 환경에 따라 달라지며 cold-start도 실행 wall time에 포함됩니다. runner는 pip/npm 설치 명령을 자동 실행하지 않습니다. OpenCode 자체 의존성 준비는 OpenCode 동작입니다.

## Offline 검증 및 config 근거

```powershell
python scripts\run_tests.py
```

테스트는 외부 모델 IO를 mock하고 실제 생성 engine의 read/edit/registry, preflight, 실패·timeout 유지, AB/BA 순서, 독립 grader, Windows npm shim을 검사합니다. macOS에서 full suite와 dry-run만 검증했습니다. **실제 Windows process tree/shell와 실제 GLM/OpenCode API 실행은 미검증**입니다.

공식 문서: [config](https://opencode.ai/docs/config/), [providers](https://opencode.ai/docs/providers/#custom-provider), [CLI run](https://opencode.ai/docs/cli/#run-1). 현재 schema URL은 v2의 `providers`/`permissions` 구조이므로 v1 config를 그대로 검증할 수 없습니다. 이 runner의 `provider`/`permission`/`agent.build.steps`/`lsp=false` 등은 [공식 v1.2.27 config 소스](https://github.com/anomalyco/opencode/blob/v1.2.27/packages/opencode/src/config/config.ts), JSON events/CLI flags는 [동일 tag run 소스](https://github.com/anomalyco/opencode/blob/v1.2.27/packages/opencode/src/cli/cmd/run.ts)와 대조했습니다. 버전 pin은 이 스키마 혼용을 방지합니다.
