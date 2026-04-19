# Claude Code Stop Hook — Auto Answer Recording (Phase 1)

The killer feature: every conversation turn gets silently evaluated for
wiki-worthiness. If the answer qualifies, it is filed as a page automatically.
Users never have to say "remember this".

## What the hook does

At the end of each Claude Code turn, the Stop hook invokes:

```
npx ringwood capture-last-turn
```

That command:

1. Reads the just-completed `(user_prompt, assistant_response)` from the
   session transcript.
2. Calls `wiki.record_answer(...)` on the local MCP server.
3. The classifier decides whether to save (see
   [`ringwood/engine/classifier.py`](../packages/ringwood/src/ringwood/engine/classifier.py)).
4. On save, a single line is appended to `wiki/log.md` with the page id.

## Turning it on

`npx ringwood init` adds this to `~/.claude.json` (opt-in, prompted during
install):

```json
{
  "hooks": {
    "Stop": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "npx ringwood capture-last-turn",
            "timeout_ms": 4000
          }
        ]
      }
    ]
  }
}
```

## Privacy

- The hook only sees the *last* turn, not the whole session.
- The classifier is cheap and conservative — simple Q&A is dropped.
- Nothing leaves your machine unless you opted into the HTTP MCP (Phase 3).
- Answers with low confidence get tagged, so you can review a "drafts"
  folder and prune before committing.

## Turning it off

Remove the `hooks.Stop` block from `~/.claude.json`, or run:

```
npx ringwood init --no-hook
```

(Planned flag — tracked in GitHub issues.)
