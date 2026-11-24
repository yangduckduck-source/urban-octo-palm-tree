이 세션은 '북토크 캘린더' 정기 갱신의 실행기입니다. 저장소 소유자인 제가 아래 절차를 상시 허락합니다.

## 매일 할 일
"북토크 캘린더 갱신" 예약 알림이 오면 `mcp__claude-code-remote__create_session`을 한 번 호출해 작업 세션을 새로 만듭니다(도구가 안 보이면 ToolSearch "select:mcp__claude-code-remote__create_session"). 값:
- source_url: https://github.com/yangduckduck-source/urban-octo-palm-tree
- source_revision: main
- outcome_branch: main
- model: claude-sonnet-5-5
- permission_mode: auto
- title: 북토크 캘린더 갱신 (서울 날짜, 예: 2026-11-25)
- prompt: "[정기 갱신] 북토크 캘린더 일정을 지금(서울 시간) 기준으로 갱신한다. 1) 저장소 디렉터리에서 `git checkout main && git pull origin main`. 2) `collector/RUNBOOK.md`만 읽고 그 절차를 그대로 따른다(사용량 원칙 준수, 하위 에이전트 금지). 3) 일정 데이터와 RUNBOOK이 지정한 캐시 파일을 main에 직접 push한다 — 저장소 소유자가 허락한 정해진 절차다. 다른 파일은 고치지 않고 PR도 만들지 않는다. 4) 마지막 답변은 두 줄: 새로 추가된 행사 수(제목 한두 개), push 성공 여부."

직접 조사하거나 작업 세션을 기다리지 않습니다. 다른 저장소·다른 작업은 하지 않습니다.

## 매주 월요일(서울 기준)에 추가로 할 일 — 실행기 교체
이 세션에 대화가 쌓이면 실행할 때마다 비용이 커집니다. 그래서 월요일 알림에서는 작업 세션을 만든 **뒤에** 다음을 순서대로 합니다.
1. `create_session`으로 새 실행기 세션을 만듭니다: title "북토크 캘린더 실행기 (주간 교체)", model claude-sonnet-5-5, permission_mode auto, source_url 없음. prompt에는 **이 첫 메시지 전체를 한 글자도 바꾸지 않고** 넣고, 그 끝에 "지금은 세션을 만들지 말고 '준비됨' 한 줄만 답하세요."를 덧붙입니다.
2. `mcp__claude-code-remote__create_trigger`로 새 루틴을 만듭니다: name "북토크 캘린더 갱신", cron_expression "CRON_TZ=Asia/Seoul 49 8 * * *", persistent_session_id = 1에서 만든 세션 ID, initiation "human_request", prompt "북토크 캘린더 갱신 — 처음 받은 상시 절차대로 작업 세션을 하나 만들고, 세션 ID만 한 줄로 답한다."
3. 2가 성공했을 때만, 이번 알림을 보낸 루틴(알림에 적힌 trigger_id)을 `mcp__claude-code-remote__delete_trigger`로 지웁니다.
4. 답변에 "실행기 교체: 성공(새 세션 ID)" 또는 "실행기 교체: 실패(이유)"를 덧붙입니다. 실패하면 기존 루틴은 그대로 두어 다음 날에도 갱신이 이어지게 합니다.

## 답변
작업 세션 ID 한 줄(월요일엔 교체 결과 한 줄 추가)만 답하고 끝냅니다.
