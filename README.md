# 북토크 캘린더

서울·청주에서 열리는 **문학·글쓰기·철학·인문학** 북토크와 강연을 모아 달력으로 보여 주는 웹앱입니다.
매일 오전·저녁 두 번 웹을 검색해 새로 발견한 행사만 더하고, 그날의 추천·이번 주 추천·이번 주 새로 추가된 행사를 맨 위에 보여 줍니다.

```
site/                 웹앱 (GitHub Pages로 배포)
  index.html, app.js, style.css
  data/events.json    일정 데이터
  calendar.ics        Apple 캘린더·구글 캘린더 구독용
collector/
  RUNBOOK.md          하루 두 번 루틴이 따르는 수집 절차
  config.toml         검색 미션·관심사 설명·미션별 조사 간격(회차)
  cache/state.json    미션별 마지막 조사 회차·검색어 순번, 막힌 URL, 재확인 기록
  cache/known.tsv     이미 달력에 있는 앞으로의 행사 (루틴은 이것만 보고 아는 행사를 건너뛴다)
  collect.py          정리 → 중복 병합 → 점수 → 저장
  scoring.py          추천 점수 규칙
.github/workflows/update.yml   main에 일정이 올라오면 Pages로 배포
```

## 동작 방식

별도 API 비용 없이 Claude 구독 안에서 돌아갑니다.

1. 매일 08:49(KST) **"북토크 캘린더 갱신 (오전)"**, 18:00(KST) **"북토크 캘린더 갱신 (저녁)"** 루틴이
   **실행마다 새 세션**을 열고(지난 대화를 이어 가지 않아 사용량이 쌓이지 않음) `collector/RUNBOOK.md`를 따릅니다.
2. `collect.py --brief`가 이번 회차 계획을 짭니다. 미션은 `every`(1=매 회차, 2=하루 한 번, 3=하루 반마다) 간격으로 돌고,
   미션마다 검색어 3개·페이지 1개만 실행마다 돌아가며 건네줍니다. 이미 달력에 있는 행사 목록도 함께 보여 주어
   루틴은 **처음 보는 행사만** 조사해 `inbox.json`에 적습니다.
3. `collect.py --ingest`가 서울·청주 밖의 행사와 지난 행사를 거르고, 같은 날 비슷한 제목이나 같은 연사를 가진 항목을 하나로 합치고,
   추천 점수를 매겨 `events.json`·`calendar.ics`를 씁니다. 이미 있는 일정과 합칠 때는 공식 공지로 확인된 정보를 우선합니다.
4. 루틴이 `main`에 push하면 GitHub Actions가 사이트를 다시 배포합니다.

미션을 추가하거나 검색어·관심사를 바꾸려면 `config.toml`만 고치면 다음 날부터 반영됩니다.

## 처음 한 번만 설정

저장소 *Settings → Pages → Build and deployment → Source* 를 **GitHub Actions** 로 바꿉니다.
그 뒤 *Actions → 북토크 캘린더 배포 → Run workflow* 를 한 번 누르면
`https://yangduckduck-source.github.io/urban-octo-palm-tree/` 에 달력이 열립니다.

## 추천 점수

| 신호 | 반영 |
|---|---|
| 주제 | 글쓰기 30 · 문학 28 · 철학 25 · 인문 18 (여러 분야에 걸치면 가산) |
| 형식 | 워크숍 13 · 북토크/대담 12 · 강좌 11 · 강연 10 · 낭독회 9 |
| 창작 신호 | 제목·소개에 창작·퇴고·문장·평론·편집자·철학 같은 단어가 있으면 최대 +12 |
| 관심사 적합도 | Claude가 매긴 0~1 값 × 22 |
| 연사 무게감 | 0~1 × 14 |
| 그 밖에 | 도서전·축제 +4, 공식 확인 +5 / 추정 −6, 시간 미정 −2, 어린이 −40 · 청소년 −30 · 참여 제한 −18 |

- **오늘의 추천**: 오늘 일정을 점수 순으로 최대 3개. 없으면 2주 안에서 가장 가까운 추천 하나.
- **이번 주 추천**: 오늘부터 일요일까지(3개 미만이면 앞으로 7일) 점수에서 하루 멀어질 때마다 0.8점을 뺀 순서로 5개.
- **이번 주 새로 추가된 행사**: 이번 주 월요일 이후 수집기가 처음 발견한(`first_seen`) 앞으로의 행사.

## 직접 실행

```bash
python3 collector/collect.py --brief                         # 오늘의 조사 계획 보기
python3 collector/collect.py --ingest collector/inbox.json  # 조사 결과 병합
python3 collector/collect.py --rescore                      # 점수만 다시 계산
python3 -m http.server -d site 8000                         # http://localhost:8000
```

API 키가 있다면 `pip install -r collector/requirements.txt` 후 `python3 collector/collect.py`로
루틴 없이 Claude API가 직접 검색하게 할 수도 있습니다(사용량만큼 API 요금이 나갑니다).
