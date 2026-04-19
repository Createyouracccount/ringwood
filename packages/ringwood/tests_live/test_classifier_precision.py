"""Live test: record_answer classifier precision.

The classifier decides whether a Q&A is wiki-worthy. False positives (saving
trash) pollute the wiki; false negatives (missing decisions) lose compounding
value. 10 labeled cases let us measure both rates at once.

Reference: PLAN.md §7 "안티패턴 회피" — mem0's 97.8% junk rate is the
specific anti-pattern this test exists to prevent.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from ringwood import Wiki
from ringwood.engine.classifier import classify

from .conftest import skip_without_key


@dataclass
class Case:
    id: str
    question: str
    answer: str
    expected_save: bool
    rationale: str


# 10 cases balanced 5/5 save/reject. Labeled by hand.
CASES: list[Case] = [
    # --- expected SAVE ---
    Case(
        "SAVE-01",
        "우리 CI 에서 어떤 테스트 러너를 쓰지?",
        "pytest. pytest-xdist 로 병렬 실행하고 marker 로 slow 그룹 분리. "
        "커버리지는 pytest-cov 로 수집해서 codecov 에 업로드.",
        True,
        "multi-tool synthesis — pytest + xdist + cov",
    ),
    Case(
        "SAVE-02",
        "API 응답 에러 포맷 어떻게 통일하기로 했어?",
        "RFC 7807 Problem Details 포맷으로 통일. 필드는 type/title/status/detail/instance. "
        "하위 호환을 위해 legacy 응답도 6개월간 병행 지원.",
        True,
        "team decision + deadline",
    ),
    Case(
        "SAVE-03",
        "이거 기억해줘: 우리 스테이징 배포는 금요일 금지.",
        "알겠어, 금요일 스테이징 배포 금지 정책을 기록해둘게.",
        True,
        "explicit save phrase",
    ),
    Case(
        "SAVE-04",
        "Postgres vs MongoDB 어느 쪽이 우리 유즈케이스에 맞지?",
        "우리는 관계형 스키마가 강하게 나와서 Postgres 가 맞음. "
        "MongoDB 는 쓰기 많은 로그성 데이터에만 제한적으로 쓸 생각. "
        "조인 빈도, 트랜잭션, 스키마 경직성 세 축에서 Postgres 가 이김.",
        True,
        "named comparison",
    ),
    Case(
        "SAVE-05",
        "아, 실은 이전에 API 버저닝은 URL 경로로 한다 했던 거 취소.",
        "헤더 기반 버저닝(Accept-Version)으로 변경. 이유는 CDN 캐시 키 충돌 방지.",
        True,
        "correction of prior decision",
    ),
    # --- expected REJECT ---
    Case(
        "REJECT-01",
        "안녕",
        "안녕하세요! 무엇을 도와드릴까요?",
        False,
        "greeting",
    ),
    Case(
        "REJECT-02",
        "1 + 1 은?",
        "2 입니다.",
        False,
        "trivial computation",
    ),
    Case(
        "REJECT-03",
        "지금 몇 시야?",
        "시스템 시계 기준 오후 3시 24분입니다.",
        False,
        "ephemeral fact",
    ),
    Case(
        "REJECT-04",
        "Python 의 len() 은 무엇을 반환해?",
        "시퀀스 길이(정수)를 반환합니다.",
        False,
        "trivial language fact any model regenerates",
    ),
    Case(
        "REJECT-05",
        "오늘 날씨 어때?",
        "죄송하지만 실시간 날씨 정보를 조회할 수 없어요.",
        False,
        "apology / no-info",
    ),
]


@skip_without_key
@pytest.mark.parametrize("case", CASES, ids=[c.id for c in CASES])
def test_classifier_decision(live_wiki: Wiki, case: Case):
    """Per-case assertion. When this fires, the rationale tells us why."""
    verdict = classify(case.question, case.answer, llm=live_wiki.llm)
    assert verdict.save == case.expected_save, (
        f"{case.id}: expected save={case.expected_save}, got {verdict.save}\n"
        f"  label: {case.rationale}\n"
        f"  engine: {verdict.rationale!r}\n"
        f"  page_type: {verdict.page_type}"
    )


@skip_without_key
def test_classifier_aggregate_precision(live_wiki: Wiki, capsys):
    """Aggregate precision/recall across the 10 cases.

    Prints a per-case table even on success so the evaluator can see
    where the model wavers — this is the single most important quality
    metric for the compounding promise.
    """
    true_pos = true_neg = false_pos = false_neg = 0
    rows = []

    for case in CASES:
        verdict = classify(case.question, case.answer, llm=live_wiki.llm)
        got = verdict.save
        want = case.expected_save
        ok = got == want
        if want and got:
            true_pos += 1
            label = "TP"
        elif not want and not got:
            true_neg += 1
            label = "TN"
        elif want and not got:
            false_neg += 1
            label = "FN (missed save)"
        else:
            false_pos += 1
            label = "FP (junk)"
        rows.append((case.id, label, ok, verdict.rationale[:60]))

    # Pretty-print the matrix for the terminal log.
    with capsys.disabled():
        print("\n┌── classifier precision ───────────────────────")
        for cid, label, ok, rationale in rows:
            mark = "✓" if ok else "✗"
            print(f"│ {mark} {cid:<12} {label:<18} {rationale}")
        precision = true_pos / max(1, true_pos + false_pos)
        recall = true_pos / max(1, true_pos + false_neg)
        acc = (true_pos + true_neg) / len(CASES)
        print(f"├── accuracy  {acc:.0%}  precision {precision:.0%}  recall {recall:.0%}")
        print(f"└── TP={true_pos}  FP={false_pos}  FN={false_neg}  TN={true_neg}")

    # Reasonable bar for a Haiku-backed classifier on this set.
    assert (true_pos + true_neg) / len(CASES) >= 0.8, "classifier accuracy < 80%"
    assert false_pos <= 1, f"too many junk-saves: {false_pos} (bar: ≤1)"
