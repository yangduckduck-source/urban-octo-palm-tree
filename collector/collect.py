"""서울·청주·대전·세종 문학/인문/철학 북토크·강연 수집기.

실행 흐름
  1. config.toml 의 미션마다 Claude에게 웹 검색(web_search)·페이지 열람(web_fetch)을 시켜 조사 노트를 받는다.
  2. 조사 노트를 정해진 JSON 형식으로 추출한다(structured outputs).
  3. 지역·날짜·대상으로 거르고, 중복을 합치고, 기존 events.json 과 병합한다.
  4. scoring.py 규칙으로 추천 점수를 매기고 events.json 과 calendar.ics 를 쓴다.

사용법
  python collector/collect.py --brief                         # 루틴용 오늘의 조사 계획 (이미 아는 행사·오늘 할 미션)
  python collector/collect.py --ingest collector/inbox.json  # 루틴이 찾은 행사 병합 (API 불필요)
  python collector/collect.py               # API로 직접 수집 (ANTHROPIC_API_KEY 필요, 선택)
  python collector/collect.py --mission 청주  # 이름에 '청주'가 들어간 미션만
  python collector/collect.py --rescore     # 검색 없이 점수·ics만 다시 계산
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import re
import sys
import tomllib
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from scoring import score_event

ROOT = Path(__file__).resolve().parent.parent
CONFIG = Path(__file__).resolve().parent / "config.toml"
DATA = ROOT / "site" / "data" / "events.json"
ICS = ROOT / "site" / "calendar.ics"
CACHE = Path(__file__).resolve().parent / "cache"
STATE = CACHE / "state.json"      # 미션별 마지막 조사일·검색어 순번, 막힌 URL, 재확인한 행사 (커밋)
KNOWN = CACHE / "known.tsv"       # 이미 달력에 있는 앞으로의 행사 목록 — 루틴은 이것만 읽고 events.json은 열지 않는다 (커밋)
PLAN = CACHE / "plan.json"        # --brief 가 정한 오늘의 계획, --ingest 가 소비 (커밋 안 함)
KST = timezone(timedelta(hours=9))

CITIES = ("서울", "청주", "대전", "세종", "온라인")  # 온라인: 줌·유튜브 라이브 등 어디서나 참여 가능한 행사
CATEGORIES = ["글쓰기", "문학", "철학", "인문"]
FORMATS = ["북토크", "강연", "강좌", "대담", "낭독회", "워크숍", "축제", "기타"]
AUDIENCES = ["성인", "누구나", "가족", "청소년", "어린이", "제한"]
CONFIDENCES = ["확정", "보도", "추정"]
PRICES = ["무료", "유료", "미확인"]

EVENT_SCHEMA = {
    "type": "object",
    "properties": {
        "events": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "행사명. 시리즈면 '시리즈명 - 회차/연사'"},
                    "date": {"type": "string", "description": "YYYY-MM-DD. 모르면 빈 문자열"},
                    "start": {"type": "string", "description": "HH:MM 24시간제. 모르면 빈 문자열"},
                    "end": {"type": "string", "description": "HH:MM. 모르면 빈 문자열"},
                    "city": {"type": "string", "enum": ["서울", "청주", "대전", "세종", "온라인", "기타"]},
                    "venue": {"type": "string"},
                    "speakers": {"type": "array", "items": {"type": "string"}},
                    "book": {"type": "string", "description": "관련 도서 제목. 없으면 빈 문자열"},
                    "categories": {"type": "array", "items": {"type": "string", "enum": CATEGORIES}},
                    "format": {"type": "string", "enum": FORMATS},
                    "audience": {"type": "string", "enum": AUDIENCES},
                    "festival": {"type": "string", "description": "도서전·독서대전·축제 이름. 아니면 빈 문자열"},
                    "price": {"type": "string", "enum": PRICES},
                    "price_note": {"type": "string"},
                    "registration": {"type": "string", "description": "신청 방법·기간"},
                    "url": {"type": "string", "description": "가장 믿을 만한 출처 URL"},
                    "summary": {"type": "string", "description": "무슨 이야기를 하는 자리인지 1~2문장"},
                    "confidence": {"type": "string", "enum": CONFIDENCES},
                    "relevance": {"type": "number", "description": "독자 관심사 적합도 0~1"},
                    "speaker_weight": {"type": "number", "description": "연사의 문학·인문 분야 무게감 0~1"},
                },
                "required": [
                    "title", "date", "start", "end", "city", "venue", "speakers", "book",
                    "categories", "format", "audience", "festival", "price", "price_note",
                    "registration", "url", "summary", "confidence", "relevance", "speaker_weight",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["events"],
    "additionalProperties": False,
}

FALLBACK_HEADERS = {"anthropic-beta": "server-side-fallback-2026-07-01"}
FALLBACK_BODY = {"fallbacks": "default"}


# ── 조사 & 추출 ─────────────────────────────────────────────

def research(client, cfg: dict, mission: dict, today: date) -> str:
    g = cfg["general"]
    until = today + timedelta(days=g["horizon_days"])
    months = sorted({f"{d.year}년 {d.month}월" for d in (today, today + timedelta(days=30), until)})
    queries = [
        q.replace("{month}", months[0]).replace("{nextmonth}", months[min(1, len(months) - 1)])
        .replace("{year}", str(today.year)) for q in mission["queries"]
    ]
    urls = "\n".join(f"- {u}" for u in mission.get("urls", [])) or "- (없음)"

    prompt = f"""오늘은 {today.isoformat()}({'월화수목금토일'[today.weekday()]}요일)입니다.
{today.isoformat()} ~ {until.isoformat()} 사이에 {mission['city'] if mission['city'] != '둘 다' else '서울·청주·대전·세종'}에서 열리는
문학·글쓰기·철학·인문학 분야의 북토크, 작가와의 만남, 강연, 강좌, 낭독회, 대담을 최대한 많이 찾아 주세요.
줌·유튜브 라이브 같은 온라인 행사도 찾아 주세요(지역 무관, city는 '온라인').
도서전·독서대전·북페스티벌 안에서 열리는 강연과 북토크도 각각 따로 찾아야 합니다. 무료·유료 모두 포함합니다.

조사 대상: {mission['name']}
검색 출발점 (이 밖에도 자유롭게 검색하세요; 다음 달 일정({', '.join(months)})도 찾아보세요):
{chr(10).join('- ' + q for q in queries)}
직접 열어볼 만한 일정 페이지:
{urls}

독자 프로필:
{cfg['profile']['description'].strip()}

규칙
- 날짜가 지난 행사, 서울·청주·대전·세종 밖의 오프라인 행사는 버리세요. 온라인 행사는 포함합니다.
- 기사가 작년 행사를 다루는지 반드시 연도를 확인하세요. 작년 일정을 올해로 옮겨 적으면 안 됩니다.
- 시리즈 강연은 회차마다 날짜·연사를 따로 적으세요.
- 날짜·시간·장소·연사·관련 도서·비용·신청 방법·출처 URL을 행사마다 적으세요. 모르는 항목은 '미확인'이라고 쓰세요.
- 공식 공지에서 확인한 일정인지, 기사 보도만 있는지, 추정인지 구분해서 적으세요.

마지막 답변은 찾은 행사를 하나씩 나열한 조사 노트로 끝내세요."""

    tools = [
        {"type": "web_search_20260209", "name": "web_search", "max_uses": g["max_searches_per_mission"],
         "user_location": {"type": "approximate", "country": "KR", "timezone": "Asia/Seoul"}},
        {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": g["max_fetches_per_mission"]},
    ]
    messages = [{"role": "user", "content": prompt}]
    for _ in range(4):  # pause_turn 이어가기
        resp = client.messages.create(
            model=g["model"],
            max_tokens=16000,
            tools=tools,
            output_config={"effort": g["research_effort"]},
            messages=messages,
            extra_headers=FALLBACK_HEADERS,
            extra_body=FALLBACK_BODY,
        )
        if resp.stop_reason == "refusal":
            raise RuntimeError("조사 요청이 거절되었습니다")
        if resp.stop_reason == "pause_turn":
            messages = [messages[0], {"role": "assistant", "content": resp.content}]
            continue
        break
    return "\n".join(b.text for b in resp.content if b.type == "text").strip()


def extract(client, cfg: dict, notes: str, today: date) -> list[dict]:
    g = cfg["general"]
    prompt = f"""오늘은 {today.isoformat()}입니다. 아래 조사 노트에서 행사를 하나씩 뽑아 JSON으로 정리하세요.

- 날짜를 특정할 수 없는 행사는 date를 빈 문자열로 두세요.
- relevance: 아래 독자에게 이 행사가 도움이 될 가능성(0~1). 글쓰기·창작 직접 관련 0.85 이상, 문학 작품 읽기 0.7~0.9,
  철학 0.7~0.85, 일반 인문 0.4~0.7, 과학·자기계발·육아는 0.3 이하.
- speaker_weight: 연사가 문학·인문 분야에서 얼마나 중요한 인물인지(0~1). 모르면 0.5.
- confidence: 공식 공지 확인=확정, 기사 보도만=보도, 날짜·장소 일부 추정=추정.
- 어린이·청소년 대상이면 audience를 그에 맞게, 특정 학교 구성원·지역 주민만 참여 가능하면 '제한'으로.

독자 프로필:
{cfg['profile']['description'].strip()}

조사 노트:
{notes}"""
    resp = client.messages.create(
        model=g["model"],
        max_tokens=16000,
        output_config={"effort": g["extract_effort"], "format": {"type": "json_schema", "schema": EVENT_SCHEMA}},
        messages=[{"role": "user", "content": prompt}],
        extra_headers=FALLBACK_HEADERS,
        extra_body=FALLBACK_BODY,
    )
    if resp.stop_reason == "refusal":
        raise RuntimeError("추출 요청이 거절되었습니다")
    text = next(b.text for b in resp.content if b.type == "text")
    return json.loads(text)["events"]


# ── 정리 ─────────────────────────────────────────────────────

def norm(s: str) -> str:
    return re.sub(r"[\s\W_]+", "", (s or "").lower())


REQUIRED_TEXT = ["title", "date", "start", "end", "city", "venue", "book", "format", "audience", "festival",
                 "price", "price_note", "registration", "url", "summary", "confidence"]


def clean(ev: dict, source: str, today: date, horizon: int) -> dict | None:
    for k in REQUIRED_TEXT:
        ev[k] = str(ev.get(k) or "").strip()
    ev["speakers"] = [str(x).strip() for x in ev.get("speakers") or [] if str(x).strip()]
    if not ev["title"] or ev["city"] not in CITIES:
        return None
    try:
        d = date.fromisoformat(ev.get("date", ""))
    except ValueError:
        return None
    if d < today or d > today + timedelta(days=horizon):
        return None
    for k in ("start", "end"):
        if not re.fullmatch(r"\d{1,2}:\d{2}", ev.get(k, "") or ""):
            ev[k] = ""
        elif len(ev[k]) == 4:
            ev[k] = "0" + ev[k]
    for k, v in list(ev.items()):
        if isinstance(v, str) and v.strip() in ("미확인", "확인 필요", "-", "없음"):
            ev[k] = ""
    ev["categories"] = [c for c in ev.get("categories") or [] if c in CATEGORIES] or ["인문"]
    ev["format"] = ev["format"] if ev["format"] in FORMATS else "기타"
    ev["audience"] = ev["audience"] if ev["audience"] in AUDIENCES else "성인"
    ev["confidence"] = ev["confidence"] if ev["confidence"] in CONFIDENCES else "보도"
    ev["price"] = ev["price"] if ev["price"] in PRICES else "미확인"
    ev["relevance"] = clamp01(ev.get("relevance"))
    ev["speaker_weight"] = clamp01(ev.get("speaker_weight"))
    ev["source"] = source
    return ev


def same_event(a: dict, b: dict) -> bool:
    if a["date"] != b["date"]:
        return False
    ta, tb = norm(a["title"]), norm(b["title"])
    if ta == tb or difflib.SequenceMatcher(None, ta, tb).ratio() > 0.72:
        return True
    sa, sb = {norm(s) for s in a.get("speakers", []) if s}, {norm(s) for s in b.get("speakers", []) if s}
    return bool(sa & sb) and (a.get("start") == b.get("start") or not a.get("start") or not b.get("start"))


def clamp01(v) -> float:
    try:
        return max(0.0, min(1.0, float(v)))
    except (TypeError, ValueError):
        return 0.5


RANK = {"확정": 3, "보도": 2, "추정": 1}


def merge_into(base: dict, new: dict) -> dict:
    better = new if RANK.get(new.get("confidence"), 0) > RANK.get(base.get("confidence"), 0) else base
    other = base if better is new else new
    out = dict(better)
    for k, v in other.items():
        if out.get(k) in ("", None, []) and v not in ("", None, []):
            out[k] = v
    out["speakers"] = list(dict.fromkeys((base.get("speakers") or []) + (new.get("speakers") or [])))
    out["categories"] = list(dict.fromkeys((better.get("categories") or []) + (other.get("categories") or [])))
    out["relevance"] = max(base.get("relevance", 0), new.get("relevance", 0))
    out["speaker_weight"] = max(base.get("speaker_weight", 0), new.get("speaker_weight", 0))
    out["id"] = base.get("id") or new.get("id")
    out["first_seen"] = base.get("first_seen") or new.get("first_seen")
    return out


def event_id(ev: dict) -> str:
    return hashlib.sha1(f"{ev['date']}|{norm(ev['title'])}".encode()).hexdigest()[:10]


def merge_all(existing: list[dict], found: list[dict], today: date, keep_past: int) -> list[dict]:
    stamp = today.isoformat()
    events = [e for e in existing if date.fromisoformat(e["date"]) >= today - timedelta(days=keep_past)]
    for ev in found:
        ev.setdefault("first_seen", stamp)
        ev["last_seen"] = stamp
        for i, cur in enumerate(events):
            if same_event(cur, ev):
                events[i] = merge_into(cur, ev)
                events[i]["last_seen"] = stamp
                break
        else:
            ev["id"] = event_id(ev)
            events.append(ev)
    return events


# ── 출력 ─────────────────────────────────────────────────────

def ics_escape(s: str) -> str:
    return (s or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def write_ics(events: list[dict]) -> None:
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//bookTalk-calendar//KO", "CALSCALE:GREGORIAN",
        "X-WR-CALNAME:북토크 캘린더", "X-WR-TIMEZONE:Asia/Seoul",
    ]
    for e in events:
        d = e["date"].replace("-", "")
        lines += ["BEGIN:VEVENT", f"UID:{e['id']}@booktalk-calendar", f"DTSTAMP:{now}"]
        if e.get("start"):
            st = e["start"].replace(":", "") + "00"
            en = (e.get("end") or "").replace(":", "") + "00" if e.get("end") else None
            if not en:
                h, m = map(int, e["start"].split(":"))
                en = f"{min(h + 2, 23):02d}{m:02d}00"
            lines += [f"DTSTART;TZID=Asia/Seoul:{d}T{st}", f"DTEND;TZID=Asia/Seoul:{d}T{en}"]
        else:
            nxt = (date.fromisoformat(e["date"]) + timedelta(days=1)).strftime("%Y%m%d")
            lines += [f"DTSTART;VALUE=DATE:{d}", f"DTEND;VALUE=DATE:{nxt}"]
        desc = "\n".join(x for x in [
            e.get("summary"), "연사: " + ", ".join(e["speakers"]) if e.get("speakers") else "",
            f"『{e['book']}』" if e.get("book") else "", e.get("registration"), e.get("url"),
        ] if x)
        lines += [
            f"SUMMARY:{ics_escape(e['title'])}",
            f"LOCATION:{ics_escape(e['city'] + ' ' + (e.get('venue') or ''))}",
            f"DESCRIPTION:{ics_escape(desc)}",
        ]
        if e.get("url"):
            lines.append(f"URL:{e['url']}")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    ICS.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")


def write_known(events: list[dict]) -> None:
    today = datetime.now(KST).date().isoformat()
    rows = ["date\ttitle\tvenue\tconfidence\tid"]
    rows += [f"{e['date']}\t{e['title']}\t{e.get('venue') or e['city']}\t{e['confidence']}\t{e['id']}"
             for e in events if e["date"] >= today]
    CACHE.mkdir(parents=True, exist_ok=True)
    KNOWN.write_text("\n".join(rows) + "\n", encoding="utf-8")


def save(events: list[dict], meta: dict) -> None:
    for e in events:
        e["score"] = score_event(e)
    events.sort(key=lambda e: (e["date"], e.get("start") or "99", -e["score"]))
    DATA.parent.mkdir(parents=True, exist_ok=True)
    DATA.write_text(json.dumps({"meta": meta, "events": events}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    write_ics(events)
    write_known(events)


# ── 루틴 사용량 절약: 오늘의 계획과 상태 ───────────────────────

def load_state() -> dict:
    st = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    st.setdefault("missions", {})
    st.setdefault("blocked_urls", [])
    st.setdefault("library_urls", {})
    st.setdefault("verified", {})
    return st


def save_state(st: dict) -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(st, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def rotate(items: list, start: int, n: int) -> list:
    if not items or n <= 0:
        return []
    start %= len(items)
    return (items[start:] + items[:start])[:min(n, len(items))]


def slot_of(now: datetime) -> int:
    """실행 회차 번호. 루틴은 하루 한 번 돌므로 날짜 번호를 그대로 쓴다(every = 며칠마다)."""
    return now.date().toordinal()


# ── 직접 수집(스크립트가 가져옴: 루틴 세션에는 페이지 열람 도구가 없다) ─────────────

UA = {"User-Agent": "Mozilla/5.0 (compatible; booktalk-calendar)"}
TOPIC = re.compile(r"북토크|작가|인문|문학|시인|소설|철학|낭독|독서|도서관|강연|특강|강좌|책")
NOISE = re.compile(r"진로|청소년|어린이|유아|경영|투자|부동산|AI|인공지능|건강|의료|치과|조합|창업|주식|코딩|선거|시장|의회|"
                   r"성료|마무리|마쳐|마쳤|성황|폐막|연수|교직원|임직원|학부모|정책")
EVENTISH = re.compile(r"강연|북토크|특강|작가와의 만남|작가 초청|북 ?콘서트|낭독|강좌|인문학|문학")


def fetch(url: str, timeout: int = 15) -> str:
    import urllib.request
    req = urllib.request.Request(url, headers=UA)
    return urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "ignore")


def article_lines(url: str, title: str, limit: int = 4) -> list[str]:
    """기사 본문에서 날짜·시간·장소·신청이 들어간 문장만 뽑는다."""
    import html as H
    try:
        b = fetch(url)
    except Exception:
        return []
    t = H.unescape(re.sub(r"<[^>]+>", "\n", re.sub(r"(?is)<(script|style).*?</\1>", "", b)))
    rows = []
    for ln in t.split("\n"):
        ln = re.sub(r"\s+", " ", ln).strip()
        if (25 < len(ln) < 400 and ln != title and ln not in rows
                and re.search(r"\d+월|\d+일|오전|오후|\d{1,2}시|신청|접수", ln)
                and re.search(r"강연|북토크|작가|특강|강좌|인문|문학|도서관|낭독|콘서트", ln)):
            rows.append(ln)
    return rows[:limit]


def news_candidates(cfg: dict, st: dict, today: date, limit: int = 8) -> tuple[list[str], list[str]]:
    """네이버 뉴스에서 지역별 최근 30일 기사 중 문학·인문 행사로 보이는 것을 골라, 본문의 날짜·장소 문장까지 붙인다.
    이미 검토한 기사는 뺀다."""
    import html as H
    import time
    import urllib.parse
    seen, out, links = set(st.get("news_seen", [])), [], []
    ds, de = (today - timedelta(days=30)).strftime("%Y.%m.%d"), today.strftime("%Y.%m.%d")
    for grp in cfg.get("news", []):
        rows, n = [], 0
        for q in grp["queries"]:
            if n >= limit:
                break  # 이 지역 후보가 충분하면 더 묻지 않는다
            time.sleep(1.0)
            u = "https://search.naver.com/search.naver?" + urllib.parse.urlencode(
                {"where": "news", "query": q, "sort": "1", "pd": "3", "ds": ds, "de": de})
            try:
                b = fetch(u)
            except Exception as exc:  # 네트워크 실패는 다음 회차에 다시
                rows.append(f"  (검색 실패: {q} — {str(exc)[:60]})")
                continue
            for m in re.finditer(r'<a[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a>', b, re.S):
                link = m.group(1)
                title = H.unescape(re.sub(r"<[^>]+>", "", m.group(2))).replace("새 창 열림", "").strip()
                if (re.search(r"naver\.com|pstatic|naver\.me", link) or len(title) < 12 or n >= limit
                        or link in seen or link in links or not TOPIC.search(title)
                        or not EVENTISH.search(title) or NOISE.search(title)):
                    continue
                links.append(link)
                n += 1
                rows.append(f"- [N{len(links)}] {title}")
                rows.append(f"    {link}")
                rows += [f"    · {x[:220]}" for x in article_lines(link, title)]
        out.append(f"### {grp['region']}")
        out += rows or ["(새 기사 없음)"]
    return out, links


def page_lines(url: str, limit: int = 15) -> list[str]:
    """도서관 게시판 페이지에서 행사로 보이는 줄만 뽑는다."""
    import html as H
    try:
        b = fetch(url)
    except Exception as exc:
        return [f"  (열지 못함: {str(exc)[:60]})"]
    t = H.unescape(re.sub(r"<[^>]+>", "\n", re.sub(r"(?is)<(script|style).*?</\1>", "", b)))
    rows = []
    for ln in t.split("\n"):
        ln = re.sub(r"\s+", " ", ln).strip()
        if 6 < len(ln) < 150 and re.search(r"강연|북토크|작가|인문|특강|문학|시인|철학|낭독", ln) and ln not in rows:
            rows.append(ln)
    return [f"    · {r}" for r in rows[:limit]] or ["    (행사로 보이는 줄 없음)"]


def brief(cfg: dict, today: date, existing: list[dict]) -> int:
    """오늘 루틴이 할 일만 짧게 출력한다. 루틴은 config·events.json 대신 이 출력만 읽는다."""
    g, st = cfg["general"], load_state()
    until = today + timedelta(days=g["horizon_days"])
    nxt = (today.replace(day=1) + timedelta(days=32)).replace(day=1)
    month, nextmonth = f"{today.year}년 {today.month}월", f"{nxt.year}년 {nxt.month}월"
    fill = lambda q: q.replace("{month}", month).replace("{nextmonth}", nextmonth).replace("{year}", str(today.year))
    qn, un = g.get("queries_per_run", 3), g.get("urls_per_run", 1)
    blocked = set(st["blocked_urls"])

    slot = slot_of(datetime.now(KST))
    plan, out = {"date": today.isoformat(), "slot": slot, "missions": [], "verify": []}, []
    out.append(f"# 오늘 {today.isoformat()}({'월화수목금토일'[today.weekday()]}) 회차"
               f" · 찾을 범위 {today.isoformat()} ~ {until.isoformat()}")
    out.append("")
    out.append("## 이번 회차에 조사할 미션 (나머지 미션은 쉬는 회차)")
    for m in cfg["missions"]:
        ms = st["missions"].get(m["name"], {})
        last = ms.get("last_slot")
        if last is not None and slot - last < m.get("every", 1):
            continue
        cur = ms.get("cursor", 0)
        qs = [fill(q) for q in rotate(m["queries"], cur, qn)]
        # always_fetch 미션(서점 행사 페이지)은 한 번 막혔던 주소도 매번 다시 연다
        urls = [u for u in m.get("urls", []) if m.get("always_fetch") or u not in blocked]
        us = rotate(urls, cur, m.get("urls_per_run", un))
        plan["missions"].append(m["name"])
        plan.setdefault("queries", {})[m["name"]] = qs
        out.append(f"### {m['name']} ({m['city']})")
        out += [f"- 검색: {q}" for q in qs]
        out += [f"- 열람: {u}" for u in us]
        if m.get("targets"):
            # 지방 도서관 직접 열람: 한 회차에 몇 곳씩 돌아가며, 찾아 둔 게시판 주소가 있으면 바로 연다
            ts = rotate(m["targets"], cur, m.get("targets_per_run", 4))
            plan.setdefault("targets", {})[m["name"]] = ts
            for t in ts:
                u = st["library_urls"].get(t)
                if u:
                    out.append(f"- 도서관: {t} — 게시판(스크립트가 읽음): {u}")
                    out += page_lines(u)
                else:
                    out.append(f"- 도서관: {t} — 주소 미확인: 검색 1회로 공식 누리집의 행사·강좌 게시판 주소를 찾아 library_urls에 적는다")
    if not plan["missions"]:
        out.append("(없음 — 오늘은 재확인만 한다)")
    else:
        total = sum(len(v) for v in plan.get("queries", {}).values())
        out.append("")
        out.append(f"→ 위 '검색:' {total}개를 **하나도 빠짐없이** 그대로 검색하고, 검색한 문장을 inbox의 \"searched\" 목록에 그대로 적는다.")
        out.append("  다 검색하지 않은 미션은 조사 완료로 기록되지 않고 다음 회차에 다시 나온다.")

    if cfg.get("news"):
        rows, links = news_candidates(cfg, st, today)
        plan["news_links"] = links
        out.append("")
        out.append("## 최근 한 달 지역·온라인 뉴스 후보 (네이버 뉴스 최근 30일, 스크립트가 기사 본문의 날짜·장소 문장까지 가져옴 · 검토 안 한 기사만)")
        out.append(f"→ 후보 {len(links)}건을 **모두** 검토하고, 검토한 번호를 inbox의 \"news_reviewed\"에 적는다(예: [\"N1\", \"N2\"]).")
        out.append("  `·` 줄(기사 본문에서 뽑은 문장)로 날짜·장소·대상을 판단한다. 모자랄 때만 한 번 검색한다. 관심 밖·지난 행사는 검토 완료로만 적는다.")
        out.append("  검토하지 않은 번호는 다음 회차에 다시 나온다.")
        out += rows

    week = (today + timedelta(days=7)).isoformat()
    cand = [e for e in existing if today.isoformat() <= e["date"] <= week
            and e.get("confidence") in ("보도", "추정") and e["id"] not in st["verified"]]
    cand.sort(key=lambda e: -e.get("score", 0))
    plan["verify"] = [e["id"] for e in cand[: g.get("verify_per_run", 3)]]
    out.append("")
    out.append("## 재확인할 행사 (공식 공지 1회 검색, 확인되면 같은 제목·날짜로 inbox에 confidence=확정)")
    out += [f"- {e['date']} {e['title']} @ {e.get('venue') or e['city']}" for e in cand[: len(plan["verify"])]] or ["(없음)"]

    upcoming = [e for e in existing if e["date"] >= today.isoformat()]
    out.append("")
    out.append(f"## 이미 아는 행사 {len(upcoming)}건 — 검색 결과에 보여도 상세 검색하지 말고 inbox에도 적지 않는다(위 재확인 대상만 예외)")
    out += [f"- {e['date'][5:]} {e['title']}" for e in upcoming]

    CACHE.mkdir(parents=True, exist_ok=True)
    PLAN.write_text(json.dumps(plan, ensure_ascii=False) + "\n", encoding="utf-8")
    print("\n".join(out))
    return 0


def finish_plan(cfg: dict, today: date, events: list[dict], blocked: list[str],
                searched: list[str] | None = None, library_urls: dict | None = None,
                news_reviewed: list[str] | None = None) -> tuple[list[str], list[str]]:
    """--brief 로 정한 계획 중 검색어를 모두 실행한 미션만 완료로 기록한다.
    반환: (완료 기록한 미션, 검색이 모자라 다음 회차로 미룬 미션)."""
    st = load_state()
    done, short = [], []
    skipped_news = 0
    did = {norm(q) for q in (searched or [])}
    if PLAN.exists():
        plan = json.loads(PLAN.read_text(encoding="utf-8"))
        if plan.get("date") == today.isoformat():
            qn = cfg["general"].get("queries_per_run", 3)
            planned = plan.get("queries", {})
            by_name = {m["name"]: m for m in cfg["missions"]}
            for name in plan.get("missions", []):
                need = planned.get(name, [])
                if need and not all(norm(q) in did for q in need):
                    short.append(f"{name} ({sum(norm(q) in did for q in need)}/{len(need)})")
                    continue
                ms = st["missions"].setdefault(name, {})
                ms["last_run"] = today.isoformat()
                ms["last_slot"] = plan.get("slot", slot_of(datetime.now(KST)))
                step = by_name.get(name, {}).get("targets_per_run", 4) if name in plan.get("targets", {}) else qn
                ms["cursor"] = ms.get("cursor", 0) + step
                done.append(name)
            nl = plan.get("news_links", [])
            ok = [nl[int(n[1:]) - 1] for n in (news_reviewed or []) if re.fullmatch(r"N\d+", str(n)) and int(str(n)[1:]) <= len(nl)]
            st["news_seen"] = (st.get("news_seen", []) + ok)[-800:]
            skipped_news = len(nl) - len(set(ok))
            for i in plan.get("verify", []):
                st["verified"][i] = today.isoformat()
        PLAN.unlink()
    st["blocked_urls"] = sorted(set(st["blocked_urls"]) | {u for u in blocked if u})
    for name, url in (library_urls or {}).items():
        if isinstance(url, str) and url.startswith("http"):
            st["library_urls"][name] = url
    ids = {e["id"] for e in events}
    st["verified"] = {k: v for k, v in st["verified"].items() if k in ids}
    save_state(st)
    if skipped_news:
        short.append(f"뉴스 후보 {skipped_news}건 미검토")
    return done, short


def load() -> tuple[list[dict], dict]:
    if not DATA.exists():
        return [], {}
    data = json.loads(DATA.read_text(encoding="utf-8"))
    return data.get("events", []), data.get("meta", {})


def ingest(path: Path, cfg: dict, today: date, existing: list[dict]) -> int:
    raw = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    blocked = raw.get("blocked_urls", []) if isinstance(raw, dict) else []
    searched = raw.get("searched", []) if isinstance(raw, dict) else []
    library_urls = raw.get("library_urls", {}) if isinstance(raw, dict) else {}
    news_reviewed = raw.get("news_reviewed", []) if isinstance(raw, dict) else []
    raw = raw.get("events", []) if isinstance(raw, dict) else raw
    before = {e["id"] for e in existing}
    horizon = cfg["general"]["horizon_days"]
    kept, log = [], {}
    for ev in raw:
        src = str(ev.get("source") or "루틴 조사")
        c = clean(dict(ev), src, today, horizon)
        stat = log.setdefault(src, {"mission": src, "found": 0, "kept": 0})
        stat["found"] += 1
        if c:
            stat["kept"] += 1
            kept.append(c)
    events = merge_all(existing, kept, today, cfg["general"]["keep_past_days"])
    added = [e for e in events if e["id"] not in before]
    save(events, {
        "updated_at": datetime.now(KST).isoformat(timespec="minutes"),
        "runs": list(log.values()),
        "count": len(events),
        "added": len(added),
    })
    done, short = finish_plan(cfg, today, events, blocked, searched, library_urls, news_reviewed)
    print(f"후보 {len(raw)}건 → 채택 {len(kept)}건 (새 행사 {len(added)}건), 달력 전체 {len(events)}건")
    print(f"검색 {len(searched)}회 기록됨")
    print(f"조사 완료로 기록한 미션: {', '.join(done) or '(없음)'}")
    if short:
        print(f"⚠ 검색을 다 하지 않아 다음 회차로 미룬 미션: {', '.join(short)}")
    for r in log.values():
        print(f"  [{r['mission']}] {r['found']} → {r['kept']}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mission", help="이름에 이 글자가 들어간 미션만 실행")
    ap.add_argument("--rescore", action="store_true", help="검색 없이 점수와 ics만 다시 계산")
    ap.add_argument("--ingest", metavar="JSON", help="루틴이 조사해 적은 행사 목록 파일을 병합")
    ap.add_argument("--brief", action="store_true", help="루틴용 오늘의 조사 계획을 출력")
    args = ap.parse_args()

    cfg = tomllib.loads(CONFIG.read_text(encoding="utf-8"))
    today = datetime.now(KST).date()
    existing, meta = load()

    if args.rescore:
        save(existing, meta)
        print(f"{len(existing)}건 점수 재계산 완료")
        return 0

    if args.brief:
        return brief(cfg, today, existing)

    if args.ingest:
        return ingest(Path(args.ingest), cfg, today, existing)

    import anthropic

    client = anthropic.Anthropic(max_retries=4)
    missions = [m for m in cfg["missions"] if not args.mission or args.mission in m["name"]]
    found, log = [], []
    for m in missions:
        try:
            notes = research(client, cfg, m, today)
            raw = extract(client, cfg, notes, today)
            kept = [c for ev in raw if (c := clean(ev, m["name"], today, cfg["general"]["horizon_days"]))]
            found += kept
            log.append({"mission": m["name"], "found": len(raw), "kept": len(kept)})
            print(f"[{m['name']}] 후보 {len(raw)} → 채택 {len(kept)}")
        except Exception as exc:  # 한 미션이 실패해도 나머지는 계속
            log.append({"mission": m["name"], "error": str(exc)[:300]})
            print(f"[{m['name']}] 실패: {exc}", file=sys.stderr)

    events = merge_all(existing, found, today, cfg["general"]["keep_past_days"])
    meta = {
        "updated_at": datetime.now(KST).isoformat(timespec="minutes"),
        "runs": log,
        "count": len(events),
    }
    save(events, meta)
    print(f"총 {len(events)}건 저장")
    return 0 if any("error" not in r for r in log) else 1


if __name__ == "__main__":
    sys.exit(main())
