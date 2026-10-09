"""추천 점수(0~100)를 매기는 규칙.

Claude가 행사마다 매긴 '관심사 적합도'(relevance)와 '연사 무게감'(speaker_weight)을 받아,
주제·형식·대상·정보 확실성 같은 객관적 신호와 섞어 하나의 점수로 만든다.
규칙이 코드에 있으므로 같은 데이터는 언제나 같은 점수를 받는다.
"""

from __future__ import annotations

CATEGORY_WEIGHT = {"글쓰기": 30, "문학": 28, "철학": 25, "인문": 18}

FORMAT_WEIGHT = {
    "워크숍": 13,
    "북토크": 12,
    "대담": 12,
    "강좌": 11,
    "강연": 10,
    "낭독회": 9,
    "축제": 6,
    "기타": 4,
}

# 제목·요약에 들어 있으면 가산하는 단어 (글쓰는 사람에게 직접 도움이 되는 신호)
CRAFT_WORDS = [
    "글쓰기", "창작", "작법", "쓰기", "퇴고", "문장", "필사", "서사", "편집자",
    "읽기", "평론", "비평", "시인", "소설가", "에세이", "수필", "합평", "낭독",
]
THOUGHT_WORDS = ["철학", "존재", "윤리", "사유", "니체", "칸트", "소크라테스", "실존", "미학"]

AUDIENCE_PENALTY = {"성인": 0, "누구나": 0, "가족": -12, "청소년": -30, "어린이": -40, "제한": -18}
CONFIDENCE_BONUS = {"확정": 5, "보도": 2, "추정": -6}


def score_event(ev: dict) -> int:
    cats = ev.get("categories") or []
    topic = max((CATEGORY_WEIGHT.get(c, 0) for c in cats), default=8)
    # 여러 관심 분야에 걸치면 조금 더
    topic += min(4, 2 * (len([c for c in cats if c in CATEGORY_WEIGHT]) - 1)) if len(cats) > 1 else 0

    fmt = FORMAT_WEIGHT.get(ev.get("format", "기타"), 4)

    text = " ".join(
        [ev.get("title", ""), ev.get("summary", ""), ev.get("book", "")]
    )
    craft = min(8, 2 * sum(1 for w in CRAFT_WORDS if w in text))
    craft += min(4, 2 * sum(1 for w in THOUGHT_WORDS if w in text))

    relevance = float(ev.get("relevance", 0.5))
    speaker = float(ev.get("speaker_weight", 0.5))

    s = topic + fmt + craft + relevance * 22 + speaker * 14
    s += 4 if ev.get("festival") else 0
    s += CONFIDENCE_BONUS.get(ev.get("confidence", "보도"), 0)
    s += AUDIENCE_PENALTY.get(ev.get("audience", "성인"), 0)
    if not ev.get("start"):
        s -= 2  # 시간이 정해지지 않은 일정은 계획 세우기 어렵다
    return max(0, min(100, round(s)))
