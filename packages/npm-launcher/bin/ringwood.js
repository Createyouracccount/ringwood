#!/usr/bin/env node
/**
 * ringwood — the 30-second installer + command surface for Claude Code.
 *
 * Subcommands:
 *   init                  — detect uv/pipx/python, install ringwood-mcp, patch
 *                           ~/.claude.json (MCP server + optional Stop hook)
 *   path                  — print the wiki root
 *   doctor                — diagnose a broken setup
 *   serve [args...]       — run the MCP server directly (advanced)
 *   capture-last-turn     — Stop-hook target (internal)
 *   stats | timeline | diff | list | show | lint
 *                         — visibility passthroughs to ringwood-cli
 *
 * Design tenets:
 *   - Never destructive. Patching ~/.claude.json always backs up first.
 *   - Idempotent. Re-running `init` is safe.
 *   - Hook install is opt-in; ask before wiring the Stop hook.
 */

"use strict";

const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const readline = require("node:readline");
const { execSync, spawnSync } = require("node:child_process");

const HOME = os.homedir();
const CLAUDE_CONFIG = path.join(HOME, ".claude.json");
const DEFAULT_WIKI_ROOT = path.join(HOME, "ringwood");
const SERVER_KEY = "ringwood";

main(process.argv.slice(2));

function main(argv) {
  const cmd = argv[0] || "init";
  try {
    switch (cmd) {
      case "init":
        return cmdInit(argv.slice(1));
      case "path":
        return cmdPath();
      case "doctor":
        return cmdDoctor();
      case "serve":
        return passthrough("ringwood-mcp", argv.slice(1));
      case "capture-last-turn":
        return passthrough("ringwood-capture", argv.slice(1));
      case "stats":
      case "timeline":
      case "diff":
      case "list":
      case "show":
      case "lint":
        return passthrough("ringwood-cli", argv);
      case "--help":
      case "-h":
      case "help":
        return printHelp();
      default:
        printHelp();
        process.exit(1);
    }
  } catch (err) {
    die(err.message || String(err));
  }
}

function printHelp() {
  console.log(`ringwood — compounding knowledge wiki for Claude Code

Install:
  npx ringwood init [--root <dir>] [--with-hook | --no-hook]
                                  Register MCP server, optionally install
                                  the Stop hook (auto-capture answers).

Inspect:
  npx ringwood stats              Growth summary for the week.
  npx ringwood timeline           Human-readable audit log.
  npx ringwood diff --days 7      What changed recently.
  npx ringwood list --kind concept
  npx ringwood show <page_id>
  npx ringwood lint               Integrity report.

Operate:
  npx ringwood path               Print the wiki root.
  npx ringwood doctor             Diagnose a broken install.
  npx ringwood serve [args...]    Run the MCP server directly.

After \`init\`, restart Claude Code and try:
  > remember: we use snake_case for filenames
  > what's our filename convention?
`);
}

// ── init ────────────────────────────────────────────────────────────────────

async function cmdInit(args) {
  const root = parseFlag(args, "--root") || DEFAULT_WIKI_ROOT;
  const rootAbs = path.resolve(expandHome(root));
  const wantHook = args.includes("--with-hook")
    ? true
    : args.includes("--no-hook")
      ? false
      : null; // decide interactively

  note(`🧠 ringwood install → ${rootAbs}`);
  fs.mkdirSync(rootAbs, { recursive: true });

  const runner = detectRunner();
  note(`✓ Python runner: ${runner.label}`);

  ensureServerInstalled(runner);
  patchClaudeConfig(runner, rootAbs);
  seedEnvTemplate(rootAbs);

  const hookDecision = wantHook === null ? await promptYesNo(
    "Install the Stop hook so Claude answers are captured automatically? [y/N] ",
    false,
  ) : wantHook;

  if (hookDecision) {
    patchStopHook(runner, rootAbs);
    note("✓ Stop hook installed (npx ringwood capture-last-turn).");
  } else {
    note("· Stop hook skipped — run with --with-hook later to enable it.");
  }

  note("");
  note("✅ Setup complete. Restart Claude Code.");
  note("");
  const envPath = path.join(rootAbs, ".env");
  if (fs.existsSync(envPath) && !hasKeyInEnv(envPath)) {
    note("🔐 To enable the LLM-backed engine, add your API key:");
    note(`   $EDITOR ${envPath}`);
    note("   (uncomment ANTHROPIC_API_KEY=...)");
    note("");
    note("   Offline mode still works (rule-based fallback).");
    note("");
  }
  note("Try it:");
  note("  > remember: we use snake_case for filenames");
  note("  > what's our filename convention?");
  note("");
  note("Wiki data: " + rootAbs);
  note("See growth: npx ringwood stats");
}

function seedEnvTemplate(rootAbs) {
  const target = path.join(rootAbs, ".env");
  if (fs.existsSync(target)) return; // never clobber user secrets

  const template = `# ringwood environment — this file is local to your wiki and never committed.
#
# Uncomment and set to enable the Haiku/Sonnet-backed engine.
# Without a key the wiki still works (rule-based classifier + regex decision),
# it just won't judge answers as intelligently.
#
# Get a key at https://console.anthropic.com/
# ANTHROPIC_API_KEY=sk-ant-...

# Optional model overrides (defaults are fine):
# WIKI_HAIKU_MODEL=claude-haiku-4-5
# WIKI_SONNET_MODEL=claude-sonnet-4-6

# Force a specific provider: "anthropic" | "stub"
# WIKI_LLM_PROVIDER=anthropic
`;
  fs.writeFileSync(target, template, { mode: 0o600 });
  note(`✓ Wrote env template → ${target}`);
  note("  (chmod 600 — readable only by your user)");
}

function hasKeyInEnv(envPath) {
  try {
    const text = fs.readFileSync(envPath, "utf8");
    return /^\s*ANTHROPIC_API_KEY\s*=\s*\S/m.test(text);
  } catch {
    return false;
  }
}

// ── path ────────────────────────────────────────────────────────────────────

function cmdPath() {
  const conf = safeReadClaudeConfig();
  const entry = conf?.mcpServers?.[SERVER_KEY];
  if (!entry) die("ringwood is not registered. Run: npx ringwood init");
  const idx = (entry.args || []).indexOf("--root");
  console.log(idx >= 0 ? entry.args[idx + 1] : DEFAULT_WIKI_ROOT);
}

// ── doctor ──────────────────────────────────────────────────────────────────

function cmdDoctor() {
  let ok = true;
  const runner = detectRunner({ softFail: true });
  if (!runner) {
    ok = false;
    warn("No Python runner found (tried: uv, uvx, pipx, python3).");
    warn('Install uv:  curl -LsSf https://astral.sh/uv/install.sh | sh');
  } else note(`✓ Python runner: ${runner.label}`);

  const conf = safeReadClaudeConfig();
  if (!conf) {
    warn(`No Claude config at ${CLAUDE_CONFIG}. Install Claude Code first.`);
    ok = false;
  } else if (!conf.mcpServers?.[SERVER_KEY]) {
    warn("ringwood is not registered. Run: npx ringwood init");
    ok = false;
  } else note(`✓ Registered in ${CLAUDE_CONFIG}`);

  if (conf?.hooks?.Stop?.some((h) =>
    (h.hooks || []).some((c) => String(c.command || "").includes("ringwood")))) {
    note("✓ Stop hook installed");
  } else {
    note("· Stop hook not installed (optional)");
  }

  process.exit(ok ? 0 : 1);
}

// ── passthrough ─────────────────────────────────────────────────────────────

function passthrough(entrypoint, extraArgs) {
  const runner = detectRunner();
  const { cmd, argv } = runner.exec(entrypoint, extraArgs);
  const result = spawnSync(cmd, argv, { stdio: "inherit" });
  process.exit(result.status ?? 1);
}

// ── runner detection ────────────────────────────────────────────────────────

function detectRunner(opts = {}) {
  const candidates = [
    {
      // Prefer a pre-installed ringwood-mcp on PATH (editable install from
      // bootstrap.sh, or a system-wide pipx/pip install). Resolve to the
      // absolute path so the MCP server still launches when Claude spawns
      // it without our PATH (e.g. outside the activated venv).
      label: "local ringwood-mcp on PATH",
      probe: () => resolveOnPath("ringwood-mcp") !== null,
      exec: (entry, args) => ({
        cmd: resolveOnPath(entry) || entry,
        argv: args,
      }),
    },
    {
      label: "uvx (recommended)",
      probe: () => which("uvx"),
      exec: (entry, args) => ({
        cmd: "uvx",
        argv: ["--from", "ringwood-mcp", entry, ...args],
      }),
    },
    {
      label: "pipx",
      probe: () => which("pipx"),
      install: () => run("pipx", ["install", "ringwood-mcp", "--force"]),
      exec: (entry, args) => ({ cmd: entry, argv: args }),
    },
    {
      label: "python3 -m",
      probe: () => which("python3"),
      install: () => run("python3", ["-m", "pip", "install", "--user", "ringwood-mcp"]),
      exec: (entry, args) => {
        // entrypoint → module path
        const modMap = {
          "ringwood-mcp": "ringwood_mcp.server",
          "ringwood-capture": "ringwood_mcp.capture",
          "ringwood-cli": "ringwood_mcp.cli",
        };
        return { cmd: "python3", argv: ["-m", modMap[entry] || entry, ...args] };
      },
    },
  ];
  for (const c of candidates) if (c.probe()) return c;
  if (opts.softFail) return null;
  die(
    "Could not find a Python runner. Install uv:\n" +
      "  curl -LsSf https://astral.sh/uv/install.sh | sh",
  );
}

function ensureServerInstalled(runner) {
  if (!runner.install) return; // uvx installs on demand
  try { runner.install(); }
  catch (e) {
    warn(`Install step failed (${e.message}). Continuing — you may need to install ringwood-mcp manually.`);
  }
}

// ── ~/.claude.json patching ─────────────────────────────────────────────────

function patchClaudeConfig(runner, wikiRoot) {
  const conf = readOrInitConfig();
  backupConfig(conf);

  conf.mcpServers = conf.mcpServers || {};
  const { cmd, argv } = runner.exec("ringwood-mcp", ["--root", wikiRoot]);
  conf.mcpServers[SERVER_KEY] = { command: cmd, args: argv, env: {} };

  writeConfig(conf);
  note(`✓ Registered "${SERVER_KEY}" in ${CLAUDE_CONFIG}`);
}

function patchStopHook(runner, wikiRoot) {
  const conf = readOrInitConfig();
  backupConfig(conf);

  const { cmd, argv } = runner.exec("ringwood-capture", ["--root", wikiRoot]);
  const commandLine = [cmd, ...argv].map(shellQuote).join(" ");

  conf.hooks = conf.hooks || {};
  conf.hooks.Stop = conf.hooks.Stop || [];

  // Remove any prior ringwood Stop hook before re-adding (idempotent).
  conf.hooks.Stop = conf.hooks.Stop
    .map((entry) => ({
      ...entry,
      hooks: (entry.hooks || []).filter(
        (h) => !String(h.command || "").includes("ringwood-capture")
            && !String(h.command || "").includes("ringwood capture-last-turn"),
      ),
    }))
    .filter((entry) => (entry.hooks || []).length > 0);

  conf.hooks.Stop.push({
    matcher: "",
    hooks: [{ type: "command", command: commandLine, timeout_ms: 4000 }],
  });

  writeConfig(conf);
}

function readOrInitConfig() {
  if (!fs.existsSync(CLAUDE_CONFIG)) {
    note(`No ${CLAUDE_CONFIG} yet; creating a new one.`);
    fs.writeFileSync(CLAUDE_CONFIG, "{}\n");
  }
  const raw = fs.readFileSync(CLAUDE_CONFIG, "utf8");
  try { return JSON.parse(raw); }
  catch {
    die(`${CLAUDE_CONFIG} is not valid JSON. Fix it or back it up before re-running.`);
  }
}

function backupConfig(conf) {
  const backup = `${CLAUDE_CONFIG}.bak-${Date.now()}`;
  fs.writeFileSync(backup, JSON.stringify(conf, null, 2) + "\n");
  note(`✓ Backed up current config to ${backup}`);
}

function writeConfig(conf) {
  fs.writeFileSync(CLAUDE_CONFIG, JSON.stringify(conf, null, 2) + "\n");
}

// ── shell helpers ───────────────────────────────────────────────────────────

function which(bin) {
  try { execSync(`command -v ${bin}`, { stdio: "ignore", shell: "/bin/sh" }); return true; }
  catch { return false; }
}
function resolveOnPath(bin) {
  // Absolute path so downstream spawners don't depend on our $PATH.
  // Whitelist the binaries we actually resolve to avoid passing user input
  // into a shell even accidentally.
  const allowed = new Set(["ringwood-mcp", "ringwood-capture", "ringwood-cli"]);
  if (!allowed.has(bin)) return null;
  try {
    const out = execSync(`command -v ${bin}`, { shell: "/bin/sh", encoding: "utf8" }).trim();
    return out || null;
  } catch { return null; }
}
function run(cmd, args) {
  const r = spawnSync(cmd, args, { stdio: "inherit" });
  if (r.status !== 0) throw new Error(`${cmd} ${args.join(" ")} exited with ${r.status}`);
}
function safeReadClaudeConfig() {
  if (!fs.existsSync(CLAUDE_CONFIG)) return null;
  try { return JSON.parse(fs.readFileSync(CLAUDE_CONFIG, "utf8")); }
  catch { return null; }
}
function parseFlag(argv, name) {
  const idx = argv.indexOf(name);
  return idx >= 0 ? argv[idx + 1] : null;
}
function expandHome(p) { return p.startsWith("~") ? path.join(HOME, p.slice(1)) : p; }
function shellQuote(s) { return /[^\w@%+=:,./-]/.test(s) ? `'${s.replace(/'/g, "'\\''")}'` : s; }
function note(msg) { process.stdout.write(msg + "\n"); }
function warn(msg) { process.stderr.write("! " + msg + "\n"); }
function die(msg) { process.stderr.write("✗ " + msg + "\n"); process.exit(1); }

async function promptYesNo(prompt, defaultValue) {
  // In non-TTY environments (CI, piped input) we can't ask; use default.
  if (!process.stdin.isTTY) return defaultValue;
  const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
  return new Promise((resolve) => {
    rl.question(prompt, (ans) => {
      rl.close();
      const v = (ans || "").trim().toLowerCase();
      if (!v) return resolve(defaultValue);
      resolve(v === "y" || v === "yes");
    });
  });
}
