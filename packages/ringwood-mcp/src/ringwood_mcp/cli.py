"""ringwood-cli — the visibility CLI.

Subcommands are the UX promise of PLAN.md §7: the user should be able to
*see* the wiki growing. Running one of these in a terminal is how that
happens without a GUI.

  stats      — week/month summary: questions, new pages, top cited
  timeline   — render log.md as a human-readable chronology
  diff       — changes in the last N days
  graph      — wikilink adjacency graph (DOT or JSON)
  list       — ids of pages, optionally filtered by kind
  show       — full markdown of a page by id
  lint       — run the integrity check and print the report

Phase 2 will add a `serve-ui` subcommand that opens a local HTML dashboard;
the CLI is the primitive surface it will be built on.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Iterable

from ringwood import Wiki


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ringwood-cli",
        description="Inspect and maintain an ringwood.",
    )
    parser.add_argument(
        "--root",
        default=os.environ.get("WIKI_ROOT", os.path.expanduser("~/ringwood")),
        help="wiki root directory (default: ~/ringwood or $WIKI_ROOT)",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_stats = sub.add_parser("stats", help="growth summary for a period")
    p_stats.add_argument("--period", choices=("day", "week", "month"), default="week")
    p_stats.add_argument("--json", action="store_true", dest="as_json")

    p_timeline = sub.add_parser("timeline", help="render log.md chronologically")
    p_timeline.add_argument("--tail", type=int, default=20, help="lines from the end")

    p_diff = sub.add_parser("diff", help="pages changed in the last N days")
    p_diff.add_argument("--days", type=int, default=7)

    p_graph = sub.add_parser("graph", help="wikilink adjacency graph")
    p_graph.add_argument(
        "--format",
        choices=("dot", "json", "text"),
        default="text",
        help="dot for Graphviz, json for tooling, text for terminal (default)",
    )
    p_graph.add_argument(
        "--include-invalid",
        action="store_true",
        help="include invalidated pages as nodes",
    )

    p_list = sub.add_parser("list", help="list page ids")
    p_list.add_argument("--kind", default=None, help="filter by kind prefix (e.g. concept)")

    p_show = sub.add_parser("show", help="print markdown of one page")
    p_show.add_argument("page_id")

    sub.add_parser("lint", help="integrity report")

    args = parser.parse_args(argv)

    root = Path(args.root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    wiki = Wiki(root=root)

    if args.cmd == "stats":
        return _cmd_stats(wiki, period=args.period, as_json=args.as_json)
    if args.cmd == "timeline":
        return _cmd_timeline(wiki, tail=args.tail)
    if args.cmd == "diff":
        return _cmd_diff(wiki, days=args.days)
    if args.cmd == "graph":
        return _cmd_graph(
            wiki, fmt=args.format, include_invalid=args.include_invalid
        )
    if args.cmd == "list":
        return _cmd_list(wiki, kind=args.kind)
    if args.cmd == "show":
        return _cmd_show(wiki, page_id=args.page_id)
    if args.cmd == "lint":
        return _cmd_lint(wiki)

    parser.print_help()
    return 1


# ── subcommands ───────────────────────────────────────────────────────────


def _cmd_stats(wiki: Wiki, *, period: str, as_json: bool) -> int:
    s = wiki.stats(period=period)
    if as_json:
        payload = {
            "period": s.period,
            "questions": s.questions,
            "pages_cited_avg": s.pages_cited_avg,
            "new_pages": s.new_pages,
            "updated_pages": s.updated_pages,
            "invalidated_pages": s.invalidated_pages,
            "top_cited": [{"page_id": pid, "cite_count": n} for pid, n in s.top_cited],
        }
        json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
        print()
        return 0

    w = 22
    print(f"📊 Wiki stats ({s.period})")
    print(f"{'questions answered':<{w}} {s.questions}")
    print(f"{'avg citations / Q':<{w}} {s.pages_cited_avg}")
    print(f"{'new pages':<{w}} {s.new_pages}")
    print(f"{'updated pages':<{w}} {s.updated_pages}")
    print(f"{'invalidated':<{w}} {s.invalidated_pages}")
    if s.top_cited:
        print()
        print("🔗 Top cited")
        for pid, n in s.top_cited:
            print(f"  {n:>4}×  {pid}")
    return 0


def _cmd_timeline(wiki: Wiki, *, tail: int) -> int:
    log = wiki.storage.read_log()
    if not log.strip():
        print("(log is empty — ingest or record an answer to seed it)")
        return 0
    lines = [ln for ln in log.splitlines() if ln.strip()]
    for ln in lines[-tail:]:
        print(ln)
    return 0


def _cmd_diff(wiki: Wiki, *, days: int) -> int:
    from datetime import date, timedelta

    cutoff = date.today() - timedelta(days=days)
    changed: list[tuple[str, str, str]] = []  # (tag, page_id, title)
    for pid in wiki.list_ids():
        try:
            p = wiki.get(pid)
        except Exception:
            continue
        if p.invalid_at is not None and p.invalid_at >= cutoff:
            changed.append(("INVAL", pid, p.title))
        elif p.created_at.date() >= cutoff:
            changed.append(("NEW", pid, p.title))
        elif p.updated_at.date() >= cutoff:
            changed.append(("UPD", pid, p.title))

    if not changed:
        print(f"(no changes in the last {days}d)")
        return 0

    changed.sort(key=lambda t: t[1])
    for tag, pid, title in changed:
        mark = {"NEW": "+", "UPD": "~", "INVAL": "✕"}[tag]
        print(f"{mark} {pid:<40} {title}")
    return 0


def _cmd_graph(wiki: Wiki, *, fmt: str, include_invalid: bool) -> int:
    g = wiki.graph(include_invalid=include_invalid)
    if not g.nodes:
        print("(no pages — wiki is empty)")
        return 0

    if fmt == "dot":
        sys.stdout.write(g.to_dot())
        return 0
    if fmt == "json":
        json.dump(g.to_json_dict(), sys.stdout, ensure_ascii=False, indent=2)
        print()
        return 0

    # text mode: per-page outgoing edges, plus broken-link section.
    out: dict[str, list[str]] = {pid: [] for pid in g.nodes}
    for src, dst in g.edges:
        out.setdefault(src, []).append(dst)

    broken: list[tuple[str, str]] = []
    print(f"🕸  {len(g.nodes)} nodes, {len(g.edges)} edges")
    for pid in sorted(g.nodes):
        if pid.startswith("?"):
            continue
        targets = out.get(pid, [])
        if not targets:
            print(f"  {pid}  (no outbound)")
            continue
        for t in targets:
            if t.startswith("?"):
                broken.append((pid, t[1:]))
            print(f"  {pid}  →  {t}")
    if broken:
        print()
        print(f"✗ {len(broken)} broken link(s):")
        for src, raw in broken:
            print(f"  {src}  →  [[{raw}]]")
    return 0


def _cmd_list(wiki: Wiki, *, kind: str | None) -> int:
    ids = wiki.list_ids(prefix=kind)
    if not ids:
        print("(no pages)")
        return 0
    for pid in ids:
        print(pid)
    return 0


def _cmd_show(wiki: Wiki, *, page_id: str) -> int:
    try:
        page = wiki.get(page_id)
    except Exception as e:
        print(f"✗ {e}", file=sys.stderr)
        return 1
    sys.stdout.write(page.to_markdown())
    return 0


def _cmd_lint(wiki: Wiki) -> int:
    report = wiki.lint()
    if report.broken_links:
        print(f"✗ broken links ({len(report.broken_links)}):")
        for pid, target in report.broken_links[:20]:
            print(f"  {pid}  →  [[{target}]]")
    if report.orphans:
        print(f"· orphans ({len(report.orphans)}):")
        for pid in report.orphans[:20]:
            print(f"  {pid}")
    if report.stale:
        print(f"· stale ({len(report.stale)}):")
        for pid in report.stale[:20]:
            print(f"  {pid}")
    if report.invalidated:
        print(f"✕ invalidated ({len(report.invalidated)})")
    if not (report.broken_links or report.orphans or report.stale or report.invalidated):
        print("✓ clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
