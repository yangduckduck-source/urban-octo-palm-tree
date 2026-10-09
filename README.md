# 북토크 캘린더

서울·청주에서 열리는 **문학·글쓰기·철학·인문학** 북토크와 강연을 모아 달력으로 보여 주는 웹앱입니다.
매일 새벽 웹을 검색해 일정을 스스로 갱신하고, 그날의 추천과 이번 주 추천을 맨 위에 보여 줍니다.

```
site/                 웹앱 (GitHub Pages로 배포)
  index.html, app.js, style.css
  data/events.json    일정 데이터 (수집기가 매일 갱신)
  calendar.ics        Apple 캘린더·구글 캘린더 구독용
collector/            수집기
  config.toml         검색 미션·관심사 설명·비용 한도
  collect.py          검색 → 추출 → 정리 → 병합 → 저장
  scoring.py          추천 점수 규칙
.github/workflows/update.yml   매일 05:40(KST) 수집 + 배포
```

## 처음 한 번만 설정

1. **이 브랜치를 `main`에 병합합니다.** 매일 도는 예약 실행은 기본 브랜치에서만 동작합니다.
2. **Pages 켜기:** 저장소 *Settings → Pages → Build and deployment → Source* 를 **GitHub Actions** 로 바꿉니다.
3. **API 키 등록:** *Settings → Secrets and variables → Actions → New repository secret*
   이름 `ANTHROPIC_API_KEY`, 값에는 [Claude Console](https://console.anthropic.com/)에서 만든 키를 넣습니다.
4. *Actions → 북토크 캘린더 갱신 → Run workflow* 로 한 번 돌려 봅니다.
   몇 분 뒤 `https://yangduckduck-source.github.io/urban-octo-palm-tree/` 에 달력이 열립니다.

키가 없으면 수집 단계는 건너뛰고, 저장된 일정만으로 사이트가 배포됩니다.

## 수집 방식

`config.toml`의 미션(서울 서점, 서울 도서관, 서울 문학관·문학재단, 서울 철학·인문 강좌, 청주 도서관·문화기관,
청주·충북 문학, 도서전·독서대전·북페스티벌)마다 따로 조사합니다.

1. **조사** — Claude가 웹 검색(`web_search`)과 일정 페이지 열람(`web_fetch`)으로 앞으로 60일 동안의 행사를 찾아 노트를 씁니다.
2. **추출** — 노트를 정해진 JSON 형식(날짜·시간·장소·연사·도서·비용·신청·출처·신뢰도)으로 바꿉니다.
3. **정리** — 서울·청주 밖의 행사와 지난 행사를 거르고, 같은 날 비슷한 제목이나 같은 연사를 가진 항목은 하나로 합칩니다.
   이미 저장된 일정과 합칠 때는 공식 공지로 확인된 정보를 우선합니다.
4. **점수** — `scoring.py` 규칙으로 0~100점 추천 점수를 매깁니다.

미션 하나가 실패해도 나머지는 계속 진행합니다. 미션을 추가하거나 검색어를 바꾸려면 `config.toml`만 고치면 됩니다.

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

## 비용

미션 8개 × (검색 최대 6회 + 페이지 열람 최대 4회)를 하루 한 번 실행합니다. 모델은 `claude-opus-5-5`입니다.
비용을 줄이려면 `config.toml`의 `model`, `max_searches_per_mission`, 미션 수를 조정하세요.

## 직접 실행

```bash
pip install -r collector/requirements.txt
export ANTHROPIC_API_KEY=...
python collector/collect.py              # 전체 수집
python collector/collect.py --mission 청주 # 일부 미션만
python collector/collect.py --rescore     # 검색 없이 점수만 다시 계산
python -m http.server -d site 8000        # http://localhost:8000
```
