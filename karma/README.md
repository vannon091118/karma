# LLM Middleware Runtime

Agent-agnostic context orchestration for any project.

Stays *between* you (human) or your agents (Claude, Hermes, OpenCode,
Cursor, Windsurf, Copilot) and the language models. Persistent per-project
memory, automatic skill selection, and a falsification gate that verifies
every result before it is trusted.

## Install

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e ./karma
karma --help
```

## Quick start

```bash
cd /path/to/your-project
karma init          # creates .karma/ (index, inventory, scopes, CLAUDE.md)
# or, guided:
karma onboard         # interactive wizard for humans new to the middleware
```

Then daily:

```bash
karma status --project your-project
karma memory get engine version_compat
karma memory set ui '{"theme":"dark"}'
karma skill list
karma dispatch "build the UI menu" --project your-project
karma prompt generate --platform claude
```

## Concepts

- **Projects** are isolated — each has its own memory, never mixed.
- **Domains** are knowledge areas (engine, runtime, ui, world, …),
  defined once in `domains/MANIFEST.json` (SSOT).
- **Skills** are reusable agent instructions, mapped to domains.
- **Falsification** tests every result before it is trusted.

See `ONBOARDING.md` (repo root) for the full human guide.
