"""서울·청주 문학/인문/철학 북토크·강연 수집기.

실행 흐름
  1. config.toml 의 미션마다 Claude에게 웹 검색(web_search)·페이지 열람(web_fetch)을 시켜 조사 노트를 받는다.
  2. 조사 노트를 정해진 JSON 형식으로 추출한다(structured outputs).
  3. 지역·날짜·대상으로 거르고, 중복을 합치고, 기존 events.json 과 병합한다.
  4. scoring.py 규칙으로 추천 점수를 매기고 events.json 과 calendar.ics 를 쓴다.

사용법
  python collector/collect.py               # 전체 수집 (ANTHROPIC_API_KEY 필요)
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
KST = timezone(timedelta(hours=9))

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
                    "city": {"type": "string", "enum": ["서울", "청주", "기타"]},
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
        q.replace("{month}", months[0]).replace("{year}", str(today.year)) for q in mission["queries"]
    ]
    urls = "\n".join(f"- {u}" for u in mission.get("urls", [])) or "- (없음)"

    prompt = f"""오늘은 {today.isoformat()}({'월화수목금토일'[today.weekday()]}요일)입니다.
{today.isoformat()} ~ {until.isoformat()} 사이에 {mission['city'] if mission['city'] != '둘 다' else '서울 또는 청주'}에서 열리는
문학·글쓰기·철학·인문학 분야의 북토크, 작가와의 만남, 강연, 강좌, 낭독회, 대담을 최대한 많이 찾아 주세요.
도서전·독서대전·북페스티벌 안에서 열리는 강연과 북토크도 각각 따로 찾아야 합니다. 무료·유료 모두 포함합니다.

조사 대상: {mission['name']}
검색 출발점 (이 밖에도 자유롭게 검색하세요; 다음 달 일정({', '.join(months)})도 찾아보세요):
{chr(10).join('- ' + q for q in queries)}
직접 열어볼 만한 일정 페이지:
{urls}

독자 프로필:
{cfg['profile']['description'].strip()}

규칙
- 날짜가 지난 행사, 서울·청주 밖의 행사(온라인 전용 포함)는 버리세요.
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


def clean(ev: dict, source: str, today: date, horizon: int) -> dict | None:
    if ev.get("city") not in ("서울", "청주"):
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
    ev["categories"] = [c for c in ev.get("categories", []) if c in CATEGORIES] or ["인문"]
    ev["relevance"] = max(0.0, min(1.0, float(ev.get("relevance", 0.5))))
    ev["speaker_weight"] = max(0.0, min(1.0, float(ev.get("speaker_weight", 0.5))))
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


def save(events: list[dict], meta: dict) -> None:
    for e in events:
        e["score"] = score_event(e)
    events.sort(key=lambda e: (e["date"], e.get("start") or "99", -e["score"]))
    DATA.parent.mkdir(parents=True, exist_ok=True)
    DATA.write_text(json.dumps({"meta": meta, "events": events}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    write_ics(events)


def load() -> tuple[list[dict], dict]:
    if not DATA.exists():
        return [], {}
    data = json.loads(DATA.read_text(encoding="utf-8"))
    return data.get("events", []), data.get("meta", {})


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mission", help="이름에 이 글자가 들어간 미션만 실행")
    ap.add_argument("--rescore", action="store_true", help="검색 없이 점수와 ics만 다시 계산")
    args = ap.parse_args()

    cfg = tomllib.loads(CONFIG.read_text(encoding="utf-8"))
    today = datetime.now(KST).date()
    existing, meta = load()

    if args.rescore:
        save(existing, meta)
        print(f"{len(existing)}건 점수 재계산 완료")
        return 0

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
