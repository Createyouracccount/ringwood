# 프로젝트 레이아웃

```
ringwood/
├── PLAN.md                          # 설계 문서
├── ARCHITECTURE.md                  # 이 파일 (레이아웃 설명)
├── README.md                        # 유저 대면 (Phase 4에서 완성)
│
├── packages/
│   ├── ringwood/                   # 순수 Python 라이브러리 (프로토콜 무관)
│   │   ├── pyproject.toml
│   │   ├── src/ringwood/
│   │   │   ├── __init__.py          # 공개 API: Wiki 클래스
│   │   │   ├── page.py              # Page 모델 (frontmatter)
│   │   │   ├── storage/
│   │   │   │   ├── __init__.py      # StorageAdapter 추상 인터페이스
│   │   │   │   ├── localfs.py       # LocalFS 구현 (Phase 0)
│   │   │   │   ├── minio.py         # MinIO (Phase 5)
│   │   │   │   └── git.py           # git remote (Phase 3)
│   │   │   ├── index/
│   │   │   │   ├── __init__.py      # IndexAdapter 추상
│   │   │   │   ├── fts5.py          # SQLite FTS5 (Phase 0, default)
│   │   │   │   └── vector.py        # LanceDB (Phase 5)
│   │   │   ├── engine/
│   │   │   │   ├── classifier.py    # 저장-가치 분류 (Haiku)
│   │   │   │   ├── contextualize.py # Contextual Retrieval 프리픽스
│   │   │   │   ├── decision.py      # ADD/UPDATE/DELETE/NOOP (Sonnet)
│   │   │   │   ├── rewriter.py      # 페이지 재작성 (Sonnet)
│   │   │   │   └── lint.py          # 주기 스윕
│   │   │   ├── api.py               # Wiki.search/get/ingest/record_answer/lint/stats
│   │   │   ├── config.py            # 설정 로딩
│   │   │   └── log.py               # log.md append-only 감사
│   │   └── tests/
│   │
│   ├── ringwood-mcp/                # ringwood를 MCP로 노출
│   │   ├── pyproject.toml
│   │   └── src/ringwood_mcp/
│   │       ├── __init__.py
│   │       ├── server.py            # FastMCP (stdio + streamable-http)
│   │       ├── tools.py             # 6개 도구 등록
│   │       └── resources.py         # wiki:// URI 리소스
│   │
│   └── npm-launcher/                # npx ringwood init
│       ├── package.json
│       ├── bin/ringwood.js          # 진입점
│       └── README.md
│
├── examples/
│   ├── basic/                       # 30초 데모용 예시 wiki 폴더
│   └── claude-code-setup/           # settings.json 예시
│
└── docs/
    ├── INSTALL.md
    └── HOOKS.md                     # Stop hook 자동 기록 설명
```

## 계층 책임 분리

| 계층 | 책임 | 의존 방향 |
|---|---|---|
| `ringwood` | 순수 로직. 저장·인덱스·엔진. 프로토콜 모름 | 없음 (표준 라이브러리 + anthropic SDK) |
| `mcp-server` | ringwood를 MCP로 노출 | `ringwood` |
| `npm-launcher` | 1줄 설치. Python 서버 스폰 + `~/.claude.json` 패치 | (별도, Node) |

**재사용성**:
- 외부 LangChain 기반 시스템은 `from ringwood import Wiki`로 직접 import → 자체 어댑터 추가
- Claude Code/Desktop는 `npx ringwood init` → 자동으로 mcp-server stdio 실행
- 팀 배포는 `mcp-server` Docker 이미지 + HTTP + OAuth

## 공개 API (ringwood)

```python
from ringwood import Wiki

wiki = Wiki(root="./wiki", storage="localfs")

# 검색
hits = wiki.search("prompt caching", limit=10)

# 페이지 조회
page = wiki.get("concept/claude-prompt-caching")

# 소스 입수 (ADD/UPDATE/NOOP 자동 결정)
result = wiki.ingest(
    text="Claude API now supports 1h TTL for prompt caching...",
    source_ref="https://anthropic.com/news/prompt-caching",
)
# → IngestResult(operation="UPDATE", page_id="...", rationale="...")

# 답변 기록 (compounding)
wiki.record_answer(
    question="What's our TS convention?",
    answer="snake_case for file names, camelCase for variables.",
    sources=[...],
)

# 점검
report = wiki.lint()
# → LintReport(broken_links=[...], stale=[...], orphans=[...], contradictions=[...])

# 성장 통계 (가시성)
stats = wiki.stats(period="week")
# → Stats(questions=23, pages_cited_avg=2.3, new_pages=14, updated=7, invalidated=2, top_cited=[...])
```
