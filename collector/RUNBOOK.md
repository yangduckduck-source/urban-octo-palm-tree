# 북토크 캘린더 일일 갱신 절차

매일 아침 Claude Code 루틴이 이 문서를 그대로 따른다. 이 문서가 유일한 지시서다.
검색은 Claude Code의 WebSearch / WebFetch 도구로 하고, 병합·중복 제거·점수 계산은 `collect.py`가 맡는다.

## 0. 준비

```bash
cd urban-octo-palm-tree   # 없으면 아래 '저장소 받기'
git checkout main && git pull origin main
```

- **저장소 받기**: 작업 디렉터리에 저장소가 없으면 `add_repo` 도구로
  `yangduckduck-source/urban-octo-palm-tree`를 push 권한으로 붙이고, 안내된 명령으로 clone한다.
- 오늘 날짜는 **서울 시간** 기준이다: `TZ=Asia/Seoul date +%F`
- `collector/config.toml`을 읽는다. `[general]`의 `horizon_days`와 `[profile]`, `[[missions]]`를 매번 새로 읽는다.

## 1. 조사

`[[missions]]`를 **처음부터 끝까지 하나도 빠짐없이** 차례로 조사한다. 미션마다 검색을 **최소 4회** 한다.
한 미션에서 결과가 없어도 다음 미션으로 넘어가 끝까지 간다. 미션마다 다음을 한다.

1. `queries`의 `{month}`를 이번 달(예: `2026년 10월`)로, `{year}`를 올해로 바꿔 검색한다.
   다음 달 이름으로도 한 번씩 검색한다. 검색어는 출발점일 뿐이니 결과를 보고 더 파고든다.
2. `urls`가 있으면 WebFetch로 열어 본다. 막힌 사이트(EGRESS_BLOCKED)는 건너뛰고 검색 결과의 요약에 의존한다.
3. 미션 하나당 검색은 대략 `max_searches_per_mission`회, 페이지 열람은 `max_fetches_per_mission`회 안에서 끝낸다.

**찾는 것**: 오늘부터 `horizon_days`일 안에 **서울 또는 청주**에서 열리는
문학·글쓰기·철학·인문학 북토크, 작가와의 만남, 강연, 강좌, 낭독회, 대담, 워크숍.
도서전·독서대전·북페스티벌 안의 강연과 북토크는 각각 따로 적는다. 무료·유료 모두 포함한다.

**규칙**
- 지난 행사, 서울·청주 밖의 행사, 온라인 전용 행사는 버린다.
- 기사가 **작년 행사**를 다루는지 연도를 반드시 확인한다. 작년 일정을 올해로 옮겨 적지 않는다.
- 시리즈 강연은 회차마다 날짜·연사를 따로 한 건씩 적는다.
- 날짜를 하루로 특정할 수 없으면 적지 않는다(달력에 올릴 수 없다).
- 지어내지 않는다. 모르는 칸은 빈 문자열로 둔다.
- **기사·보도자료·SNS 공지 어느 하나에서라도** 날짜(올해)와 장소가 나오면 기록한다. 공식 공지로 다시 확인되지 않았다는
  이유로 빼지 않는다. 그런 행사는 `confidence`를 `보도`로 적으면 된다. 달력이 각 행사에 신뢰도를 표시해 준다.
- 홈페이지가 막혀 열리지 않으면(EGRESS_BLOCKED 등) 그 사이트 이름으로 검색해서 검색 결과 요약을 쓴다. 실패로 치지 않는다.

**이미 있는 일정 다시 보기**: `site/data/events.json`에서 앞으로 7일 안에 열리고 `confidence`가 `보도` 또는 `추정`인
행사는 공식 공지를 한 번 더 찾아본다. 확인되면 같은 제목·날짜로 다시 적고 `confidence`를 `확정`으로, 시간·신청 정보를 채운다.

## 2. 기록

찾은 행사를 `collector/inbox.json`에 JSON 배열로 쓴다. 한 건의 모양:

```json
{
  "source": "서울 서점 북토크",
  "title": "보라토크 — 이정우 ‘사람이란 무엇인가’",
  "date": "2026-10-17",
  "start": "14:00",
  "end": "15:30",
  "city": "서울",
  "venue": "광화문 교보빌딩 23층 대산홀",
  "speakers": ["이정우"],
  "book": "",
  "categories": ["철학", "인문"],
  "format": "강연",
  "audience": "성인",
  "festival": "",
  "price": "무료",
  "price_note": "",
  "registration": "교보문고 문화공간 페이지에서 신청",
  "url": "https://store.kyobobook.co.kr/culture/bora-show/859",
  "summary": "AI 시대에 다시 떠오른 존재론적 질문을 의학·철학·뇌과학을 넘나들며 묻는 강연.",
  "confidence": "확정",
  "relevance": 0.7,
  "speaker_weight": 0.45
}
```

| 칸 | 값 |
|---|---|
| `source` | 미션 이름 |
| `date` / `start` / `end` | `YYYY-MM-DD` / `HH:MM`(24시간). 모르면 `""` |
| `city` | `서울` 또는 `청주` |
| `categories` | `글쓰기` `문학` `철학` `인문` 중 하나 이상 |
| `format` | `북토크` `강연` `강좌` `대담` `낭독회` `워크숍` `축제` `기타` |
| `audience` | `성인` `누구나` `가족` `청소년` `어린이` `제한`(특정 학교 구성원·지역 주민만) |
| `price` | `무료` `유료` `미확인` |
| `confidence` | 공식 공지 확인 `확정` · 기사 보도만 `보도` · 일부 추정 `추정` |
| `relevance` | `[profile]` 독자에게 도움이 될 가능성 0~1. 글쓰기·창작 직접 관련 0.85↑, 문학 작품 읽기 0.7~0.9, 철학 0.7~0.85, 일반 인문 0.4~0.7, 과학·자기계발·육아 0.3↓ |
| `speaker_weight` | 연사가 문학·인문 분야에서 갖는 무게감 0~1. 모르면 0.5 |
| `summary` | 무슨 이야기를 하는 자리인지 1~2문장 |

## 3. 병합과 저장

```bash
python3 collector/collect.py --ingest collector/inbox.json
```

이 명령이 지역·날짜를 다시 거르고, 기존 일정과 중복을 합치고, 추천 점수를 매겨
`site/data/events.json`과 `site/calendar.ics`를 쓴다. 출력된 미션별 채택 수를 확인한다.
새로 찾은 행사가 없어도 이 명령은 실행하고, 갱신 시각이 바뀐 `events.json`을 그대로 커밋한다(달력에 "몇 월 며칠 업데이트"가 표시된다).
JSON 오류가 나면 `inbox.json`을 고쳐 다시 실행한다.

## 4. 게시

```bash
git add site/data/events.json site/calendar.ics
git commit -m "일정 갱신 $(TZ=Asia/Seoul date +%F)"
git push origin main
```

`main`에 push하면 GitHub Actions가 사이트를 다시 배포한다. **이 저장소에서는 `main`에 직접 push하는 것이 정해진 절차다.**
`inbox.json`은 커밋하지 않는다(.gitignore에 있음). 이 문서와 코드는 고치지 않는다.

- push가 거부되면 `git pull --rebase origin main` 후 한 번만 다시 시도한다. 그래도 안 되면 그 사실을 보고한다.

## 5. 보고

마지막 답변은 세 줄 이내로 쓴다: 새로 추가된 행사 수, 오늘·이번 주 추천 1순위 제목, 실패한 미션이 있으면 그 이름.
