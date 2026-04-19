<p align="center"><b>ringwood</b></p>
<p align="center"><i>The memory layer your Claude has been missing.</i></p>
<p align="center">
  <a href="#install">Install</a> ·
  <a href="#use">Use</a> ·
  <a href="#does-it-actually-work">Evidence</a> ·
  <a href="#troubleshoot">Troubleshoot</a>
</p>

---

`memory.md` is Claude remembering *you*. **ringwood is you and Claude
building a brain together** — plain-text, searchable, shared across every
MCP client (Claude Code, Claude.ai, Cursor, Windsurf, Zed), and it compounds
every time you chat.

## Install

### Option A — one line from a clone (recommended while we're pre-release)

```bash
git clone https://github.com/Createyouracccount/ringwood && cd ringwood
./bootstrap.sh --hook
```

`bootstrap.sh` does the whole thing:
1. verifies Python ≥ 3.10 and Node ≥ 18
2. creates `.venv` and installs `ringwood` + `ringwood-mcp` editable
3. registers the MCP server with Claude Code (backs up `~/.claude.json` first)
4. optionally installs the Stop hook (`--hook`) so Claude's answers are
   auto-captured — no manual "save this"
5. seeds `~/ringwood/.env` with `chmod 600` so your API key is safe

### Option B — manual

```bash
uv pip install -e packages/ringwood packages/ringwood-mcp
node packages/npm-launcher/bin/ringwood.js init --with-hook
```

### Add your Anthropic key

The engine works without a key (rule-based fallback), but quality jumps
dramatically with one. Get a key at
[console.anthropic.com/settings/keys](https://console.anthropic.com/settings/keys),
then open `~/ringwood/.env` in your editor:

```bash
code ~/ringwood/.env     # VS Code
# or
nano ~/ringwood/.env     # terminal
```

Uncomment `ANTHROPIC_API_KEY=` and paste the key. Save.

### Verify it's wired up

Restart Claude Code (`exit` then reopen), then:

```bash
claude mcp list
```

You should see `ringwood: ✓ Connected`. If it hangs on "Checking…" for
more than a few seconds, jump to [Troubleshoot](#troubleshoot).

## Use

Three things a user does, in order of how often they do them.

### 1. Just chat — answers get captured automatically

If you installed with `--hook`, Claude Code runs `ringwood capture-last-turn`
after every turn. The worthiness classifier decides (conservatively) whether
to file the Q&A as a wiki page. You do nothing.

```
> remember: we use snake_case for filenames
✓ wiki ← ADD decision/snake-case-filenames

> what's our filename convention?
→ snake_case (source: wiki/decision/snake-case-filenames, cited 1×)
```

Without the hook, say **"remember …"** / **"저장해"** / **"wiki"** and the
classifier will save it on the next turn.

### 2. Ask Claude — it searches first

With the MCP server running, Claude has six wiki tools available. It calls
`search_wiki` on its own before domain questions:

```
> 우리 팀 마이그레이션 방식이 뭐였지?

📚 Referenced: wiki/decision/db-migration-two-phase (cited 3×)
   우리 팀은 두 단계 배포 방식을 씁니다: (1) 스키마만 배포해 구/신
   양쪽을 허용, (2) 애플리케이션 스위치. 롤백은 forward-only 정책…
```

Every cited page shows **how old it is** and **how often it's been used** —
the wiki grows audible over time.

### 3. Inspect your wiki

```bash
# See what the wiki actually captured this week
npx ringwood stats

📊 Wiki stats (week)
questions answered     14
avg citations / Q      2.3
new pages              9
updated pages          3
invalidated            1
🔗 Top cited
     8×  decision/db-migration-two-phase
     5×  concept/prompt-caching-economics

# Audit log — each line is one engine decision
npx ringwood timeline --tail 10

- [2026-04-19T01:42:12Z] ADD decision/asia-seoul-timezone-alerts | new policy
- [2026-04-19T01:42:30Z] SUPERSEDE decision/utc-everywhere → decision/asia-seoul-timezone-alerts

# Diff the last week
npx ringwood diff --days 7

+ decision/asia-seoul-timezone-alerts        Asia/Seoul 알림 정책
~ decision/db-migration-two-phase             두 단계 배포 방식
✕ decision/utc-everywhere                     UTC 전면 정책 (invalidated)

# Integrity check
npx ringwood lint

✓ clean
```

### Editing by hand

Everything is plain markdown in `~/ringwood/wiki/`. Open any page, edit
in `$EDITOR`, commit to git if you want team sharing. The next search call
will re-index automatically.

## Does it actually work?

We ran a head-to-head: same Sonnet 4.6 model, two paths —
**(A)** bare Claude with no context, **(B)** Claude + our wiki seeded
with the user's prior history. Same judge. Five scenarios derived from
LongMemEval-style knowledge-update tasks.

```
═══ totals: bare 1/5   wiki 4/5 ═══
```

| Dimension (5 scenarios) | Bare | Wiki | Δ |
|---|---:|---:|---:|
| Factually correct (fc=2) | 1 | 4 | **+3** |
| Factually wrong (fc=0) | 3 | 1 | −2 |
| Generic hedging (fc=1) | 1 | 0 | −1 |
| Honest abstention | 1 | 1 | 0 |

- Bare Claude said "I don't have access to your history" on 3 of 5.
- Wiki Claude pulled the right fact and cited it on 4 of 5.
- On the 1 scenario where wiki lost (compound refund-policy question),
  the retriever found zero matching pages. That's an honest bug and the
  single clearest argument for Phase 5 vector search.

Full run: [`docs/ANSWER_QUALITY_REPORT.md`](./docs/ANSWER_QUALITY_REPORT.md)
(raw answers, judge rationales, JSON dump). One full A/B sweep costs ≈ $0.15.

See also:
[`docs/QUALITY_REPORT_PHASE1.md`](./docs/QUALITY_REPORT_PHASE1.md) —
45/45 tests pass (21 offline + 24 live), 4 real bugs found and fixed.

## How it works

```
    question / answer
           │
           ▼
  ┌──────────────────┐
  │ 1. Write trigger │   Haiku 4.5 decides: worth saving?  (free / junk-pass)
  └────────┬─────────┘
           ▼
  ┌──────────────────┐
  │ 2. Contextualize │   Haiku 4.5 + prompt caching (0.1× on repeat chunks)
  └────────┬─────────┘   Anthropic's Contextual Retrieval recipe → −67% miss
           ▼
  ┌──────────────────┐
  │ 3. Hybrid search │   SQLite FTS5 (trigram; Korean-safe)
  └────────┬─────────┘   Phase 5: + embeddings + reranker
           ▼
  ┌──────────────────┐
  │ 4. Decide        │   Sonnet 4.6 picks ADD / UPDATE / DELETE / NOOP
  └────────┬─────────┘   mem0-style 4-operation schema
           │
  ┌──────────────────┐
  │ 5. Persist       │   Markdown file + bitemporal frontmatter
  └──────────────────┘   DELETE = invalidate(old) + add(new) + link
```

Storage is **just markdown files**. `ls ~/ringwood/wiki/` and you can read
everything. Commit to git to share with teammates.

## Architecture

```
ringwood/
├── docs/
│   ├── ANSWER_QUALITY_REPORT.md    this is the value proof
│   ├── QUALITY_REPORT_PHASE1.md    test-suite report
│   ├── SECURITY.md                 where secrets live
│   ├── HOOKS.md                    Stop-hook internals
│   └── INSTALL.md                  manual paths
└── packages/
    ├── ringwood/           protocol-agnostic Python library
    ├── ringwood-mcp/        ringwood exposed over MCP (stdio + HTTP)
    └── npm-launcher/        npx ringwood init
```

Three layers. Only `ringwood` contains logic; the other two are thin
adapters. Your own app can `from ringwood import Wiki` and skip MCP
entirely.

## Troubleshoot

Run the doctor first. It checks everything at once:

```bash
npx ringwood doctor
```

### "ringwood is not registered"

You haven't run `init` yet or `~/.claude.json` got replaced. Run:

```bash
npx ringwood init
```

Your previous config is always backed up at `~/.claude.json.bak-<epoch>`.

### "available: False" — LLM path isn't kicking in

```bash
python3 -c "from ringwood import Wiki; print(Wiki(root='~/ringwood').llm.available)"
```

If `False`: either `~/ringwood/.env` has no `ANTHROPIC_API_KEY`, or the key
is malformed. The engine falls back to a rule-based classifier silently —
it still works but with markedly lower quality (see A/B report).

### "Claude Code doesn't see my wiki"

Three culprits in order:
1. You didn't restart Claude Code after `init`. MCP servers are registered
   once per session.
2. The server crashed on startup. `ringwood serve` from a terminal to see
   the error.
3. The wrong Python runner. `doctor` prints which one we chose.

### `claude mcp list` hangs on "Checking…"

If `~/.claude.json` was patched with `uvx --from ringwood-mcp …` but the
package isn't on PyPI yet (i.e. you cloned from a pre-release commit), uvx
tries to download forever. Fix by re-running `bootstrap.sh` — the launcher
now prefers a local install on PATH and records its absolute path in
`~/.claude.json` instead:

```bash
cd /path/to/ringwood
./bootstrap.sh --hook
```

Verify the fix:

```bash
python3 -c "import json; c=json.load(open('~/.claude.json'.replace('~', __import__('os').path.expanduser('~')))); print(c['mcpServers']['ringwood']['command'])"
# → /absolute/path/to/ringwood-mcp  (NOT 'uvx')
```

### `permission denied: ~/ringwood/.env` when editing

`$EDITOR` isn't set, so the shell tries to "run" the `.env` file. Use a
real editor name:

```bash
code ~/ringwood/.env     # VS Code
nano ~/ringwood/.env     # terminal
vim  ~/ringwood/.env     # vim
```

(If you want `$EDITOR` set persistently: `echo 'export EDITOR=code' >> ~/.zshrc`.)

### Korean/Japanese queries miss obvious pages

This was a real bug (fixed in v0.1). If you hit it, ensure your install
is on SQLite ≥ 3.34 with trigram tokenizer support:

```bash
python3 -c "import sqlite3; c=sqlite3.connect(':memory:'); c.execute(\"CREATE VIRTUAL TABLE t USING fts5(x, tokenize='trigram')\"); print('ok')"
```

### Remove everything

```bash
make uninstall          # removes packages, keeps wiki data
rm -rf ~/ringwood        # removes wiki data
# restore pre-install ~/.claude.json from the .bak-<epoch> file
```

## Status

| Phase | Status |
|---|---|
| 0 — skeleton | ✓ 21/21 offline tests |
| 1 — compounding engine (Haiku + Sonnet) | ✓ 24/24 live tests, 4/5 A/B wins |
| 2 — polish (visibility, inline citations) | in progress (CLI shipped) |
| 3 — HTTP MCP + OAuth for teams | pending |
| 4 — public launch (PyPI + npm) | pending |
| 5 — vector index + reranker | pending |
| 6 — full evaluation harness | pending |

## License

MIT.

## Acknowledgements

- Andrej Karpathy's "Ringwood" gist for the compound-knowledge pattern
- Anthropic for [Contextual Retrieval](https://www.anthropic.com/news/contextual-retrieval)
- mem0, Zep/Graphiti, Letta for prior art on the 4-operation decision pattern
- LongMemEval (Wu et al., 2024) for the benchmark shape we borrow
