# Contributing

ringwood is pre-1.0. Breaking changes are possible but every release passes
the offline + live suites before it ships. When you submit, please do the
same.

## Development setup

```bash
git clone https://github.com/ringwood/ringwood
cd ringwood
./bootstrap.sh --dev        # editable install + test deps + runs tests
```

## Workflow

1. Create a branch from `main`.
2. Run `make test` (offline, 21 cases, no API key required). These are
   non-negotiable.
3. If you touched engine behavior, run `make test-live` (24 cases, real
   Anthropic, ≈$0.11). If you don't have a key, mention it in the PR —
   a reviewer will run them.
4. Add a test for the behavior you're changing. Every fix in 0.1 started
   with a failing test.
5. Update `CHANGELOG.md` under `[Unreleased]`.

## Code guidelines

- **Never delegate understanding to the model.** Engine modules keep both
  a rule-based fallback and an LLM path. The rule-based path must always
  run without an API key. This is how we guarantee offline usability and
  how we keep tests cheap.
- **Secrets never touch git or logs.** Loading is centralized in
  `ringwood.env`. Don't read `os.environ["ANTHROPIC_API_KEY"]` from
  elsewhere — call `get_client()`.
- **Storage is markdown.** The `wiki/` directory is the source of truth;
  `.index/` is a derived cache and must be safe to delete and rebuild.
- **One MCP tool = one job.** Adding a tool expands the context Claude
  has to reason about. Err on the side of folding behavior into existing
  tools. Anthropic's internal guidance is 5–15 tools total; we're at 6.
- **Bitemporal, always.** No hard deletes in the engine. DELETE decisions
  translate to `invalid_at` stamps. Preserve history.

## Adding a golden scenario

Edit `packages/ringwood/tests_live/golden/knowledge_updates.yaml`.
One YAML entry is one test. Use `expected_action_any: [A, B]` when both
operations produce the same user-visible effect — we test outcomes, not
engine-internal labels.

## Testing LLM behavior offline

`FakeClient` in `tests/test_llm_integration.py` implements the
`LLMClient` protocol. Return canned `Classification`/`_DecisionOut`
instances and exercise the pipeline without the network.

## Pull request checklist

- [ ] `make test` passes
- [ ] `make test-live` passes (or noted in PR description)
- [ ] New behavior has a test
- [ ] CHANGELOG updated
- [ ] No `os.environ["API_KEY"]` or similar in non-env modules
- [ ] No hard deletes added

## Reporting issues

Open a GitHub issue. For security (secret leak paths), tag the issue
`security:` so it gets triaged first. See
[docs/SECURITY.md](./docs/SECURITY.md) for the current policy.
