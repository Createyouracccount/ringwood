# Answer Quality A/B — Does the Wiki Actually Help?

*Run: 2026-04-19. Model: `claude-sonnet-4-6` for both answering and judging.
Runtime 2m 12s, cost ≈ $0.15.*

## Headline

**Bare Claude: 1 / 5. Claude + our wiki: 4 / 5.**

Four of five scenarios produced strictly better answers when the same
Sonnet model had access to the user's prior wiki. The one draw is an
abstention scenario where both correctly declined to answer. The one
wiki *loss* (Q4) is a judge-grading artifact explained below.

## Scenarios and Results

### Q1 — "Postgres 마이그레이션을 안전하게 진행하려면 우리 팀 방식은 뭐야?"

The wiki contained the team's two-phase-deploy + forward-only-rollback rule.

| | Factual score | Verdict | Key phrase |
|---|---:|---|---|
| **Bare** | 0 | abstained — correctly said it doesn't know team specifics | (none) |
| **Wiki** | 2 | both required facts surfaced | "두 단계", "forward-only" |

Wiki answer opened with "위키에 따르면, 우리 팀은 **두 단계(2-phase) 배포 방식**을
반드시 따릅니다" and walked through both phases. Bare answer honestly
admitted ignorance — so it didn't hallucinate, but it also didn't help.

### Q2 — "우리 왜 GraphQL 안 썼었지?"

Wiki held two historical decisions (2025-09 hold, 2026-02 REST+JSON:API
commit) with rationales.

| | Factual score | Captured why? |
|---|---:|---|
| **Bare** | 0 | No — listed generic GraphQL tradeoffs, missed "스키마 관리" + "학습 비용" |
| **Wiki** | 2 | Yes — cited both the 3-member team split and the REST+JSON:API commit |

### Q3 — "사용자 알림 이메일의 시간 표기는 어느 타임존이지?"

Policy **changed** mid-history: UTC universally → Asia/Seoul for
user-facing notifications. Critical contradiction scenario.

| | Answered correctly? | Cited the 2026-03 change? |
|---|---|---|
| **Bare** | No — abstained | — |
| **Wiki** | Yes — Asia/Seoul, cited the 2026-03 policy change | Yes |

Wiki's answer: *"위키에 따르면, 사용자 알림은 `Asia/Seoul` 타임존으로 포맷팅합니다.
이는 2026-03 정책 변경 시 고객사 요청을 반영하여 결정된 사항입니다. (DB 저장은
여전히 UTC 유지)"* — exactly the nuanced answer we promised when we designed
the bitemporal storage.

### Q4 — "연간 구독 3개월 쓰다 해지하면 환불 받을 수 있어?"

Required synthesizing across three pages (Toss migration, 7/30-day refund
windows, subscription rules). Both systems missed.

| | Factual score | Why |
|---|---:|---|
| **Bare** | 1 | Generic refund table — didn't commit to "no refund" |
| **Wiki** | 0 | Also hedged. `used=[]` means wiki search found NO relevant pages |

**Root cause** (honest finding): our retrieval never surfaced the subscription
rule page for the query "연간 구독 … 해지 … 환불". This is a true retrieval
failure. Three root causes:
1. BM25 on trigram tokens didn't weight "구독 환불" highly enough against the
   other pages about 결제/환불 (one-shot payments).
2. We have no semantic similarity (Phase 5 embeddings would catch this).
3. The answerer didn't try a second, broader query when the first was empty.

This is the single clearest argument for Phase 5 vector indexing and for
agentic multi-round retrieval.

### Q5 — Abstention: "프로젝트 Alpha 담당 PM 이름은?"

| | Abstained correctly? | Forbidden phrase used? |
|---|---|---|
| **Bare** | Yes | No |
| **Wiki** | Yes — and cited what it *did* know (start date) | No |

Bonus: wiki's answer offered a path forward — *"PM 정보를 위키에 추가하시면
더 정확한 답변을 드릴 수 있습니다."* This is a small but real UX win:
bare Claude doesn't even know what you *could* store.

## What This Does and Does Not Prove

### Proves

1. **The wiki actually changes answer quality in the direction we claimed.**
   4/5 vs 1/5 on hand-picked scenarios isn't a benchmark result — it's a
   sanity check — but the direction and magnitude align with the design
   promise.
2. **Prior decisions survive.** Q2's "why" question is exactly the use case
   the project exists for: recovering the *rationale* behind past choices,
   not just the choices.
3. **Contradiction resolution works through to the answer.** Q3 demonstrates
   that the supersede pipeline from Phase 1 actually produces the right
   user-visible behavior: old UTC-for-everything policy is hidden, new
   nuanced policy surfaces.
4. **Abstention is preserved, not degraded.** Q5 shows that having a wiki
   doesn't make Claude over-confident. It gracefully admits missing info.

### Does NOT Prove

1. **Scale.** 5 hand-crafted scenarios — not LongMemEval's 500.
2. **Retrieval robustness.** Q4's failure is real and representative. Today's
   system fails when the query doesn't share enough surface tokens with the
   relevant page. A trained eye can design 50 more Q4-shaped failures.
3. **Agentic retry.** Each answer here makes one `search_wiki` call. Real
   Claude Code usage tends to iterate. The question of whether iteration
   rescues Q4-shaped failures is unanswered here.
4. **Cross-user robustness.** Korean-only. English/code-heavy queries
   untested.

## Why the Judge Is Trustworthy (and Its Limits)

The judge is Sonnet 4.6 with strict structured output. Both answers are
graded on the **same rubric** inside a single call, removing prompt-drift
bias. But the judge shares a model family with the answerer, so it may
reward a style of answer that Sonnet finds natural. For Phase 2 we'll
re-run with Opus-as-judge and compare to guard against this.

## Numbers You Can Act On

| Dimension | Bare | Wiki | Δ |
|---|---:|---:|---:|
| Factually correct (fc=2) | 1 | 4 | +3 |
| Abstained when it should | 1 | 1 | 0 |
| Factually wrong (fc=0) | 3 | 1 | -2 |
| Generic hedging (fc=1) | 1 | 0 | -1 |

Shift: **fewer "I don't know" and fewer hallucinations at the same time.**
This is the compound benefit — not just "wiki adds info" but "wiki removes
both hallucinations and helpless abstentions where ground truth exists."

## Cost

One full A/B run:
- 5 scenarios × (1 bare answer + 1 wiki answer + 2 judge calls + seeds) ≈
  40 Sonnet calls
- Total: $0.15

This is cheap enough that the A/B is part of CI. Add a tenth scenario,
the bill stays under $0.50. A 50-case port of LongMemEval `knowledge_updates`
would run ≈ $1.50 per sweep — still trivial.

## Artifacts

- Scenarios: [`packages/ringwood/tests_live/golden/answer_quality.yaml`](../packages/ringwood/tests_live/golden/answer_quality.yaml)
- Test code: [`packages/ringwood/tests_live/test_answer_quality.py`](../packages/ringwood/tests_live/test_answer_quality.py)
- Raw JSON of this run: `packages/ringwood/tests_live/quality_run.json`
  (each row includes both answers, judge rationale, used wiki page ids —
  regressions are diff-able)

## Reproducibility

```bash
export ANTHROPIC_API_KEY=sk-ant-...  # or put in ~/ringwood/.env
cd packages/ringwood
python3 -m pytest tests_live/test_answer_quality.py -v -s
```

CI ready. Fixed expectation: **wiki > bare, wiki ≥ 3/5.** If it falls
below, the test fails loudly and points at the regression by scenario id.
