# CLAUDE.md

Cedric owns this. Start: say hi + 1 motivating line.
Work style: telegraph; noun-phrases ok; drop grammar; min tokens.

## Identity
- Owner: cdrc1103
- Workspace root: `~/ai_research`
- Own projects: `~/ai_research/mine/`
- Reference/collab: `~/ai_research/others/`

Missing own repo: clone `git@github.com:cdrc1103/<repo>.git` into `mine/`.
3rd-party/reference: clone under `others/`.

## Agent Protocol
- Files: inside repo, or `~/ai_research/agent-scripts/` for standalone scripts.
- PRs: use `gh pr view/diff` (not URLs).
- "Make a note" => edit this CLAUDE.md. Not a blocker; skip if mid-task.
- Guardrails: use `trash` for deletes (never bare `rm`).
- Need upstream file: stage in `/tmp/`; never overwrite tracked files directly.
- Bugs: add regression test when it fits naturally.
- Keep files <~500 LOC; split/refactor proactively.
- Commits: Conventional Commits — `feat|fix|refactor|build|ci|chore|docs|style|perf|test`.
- Editor: `code <path>`.
- CI: `gh run list/view`; rerun/fix until green.
- Prefer end-to-end verify; if blocked, say what's missing.
- New deps: health-check (recent releases, active maintainers, adoption).
- Web: search early; quote exact errors; prefer 2025 sources.

## Git
- Safe default: `git status/diff/log`. Push only when asked.
- Remote: SSH (`git@github.com:cdrc1103/...`).
- Aliases on PATH: `ga` (add), `gm` (commit -m), `gp` (push). Use them.
- Pager: `delta` (side-by-side). Big diffs: `git --no-pager diff --color=never`.
- Destructive ops forbidden unless explicit: `reset --hard`, `clean`, `restore`, `rm`.
- No amend unless asked. No branch rename/delete without consent.
- Multi-agent: check `git status/diff` before edits; ship small commits.
- Default branch: `main`.

## Stack & Runtime
- Python 3.12 (primary for AI/ML projects). **`uv` is the ONLY dependency manager.** Never use `pip`, `pip install`, `python -m pip`, or `pipx` directly. Always: `uv add`, `uv sync`, `uv run`. Don't touch system pip.
- Node 22 via NVM. Use repo's package manager; no swaps without approval.
- AWS tools present (`~/.aws/`). Don't touch credentials; ask before infra changes.

## Build / Test
- Before handoff: lint + typecheck + tests (per-repo gate; check Makefile/scripts).
- CI red: `gh run list/view`, fix, push, repeat until green.
- Each project has its own CLAUDE.md — read it first before coding.
- Release: find checklist in `docs/RELEASING.md` or repo root.

## Critical Thinking
- Fix root cause, not band-aid.
- Unsure: read more code; if still stuck, ask with short options.
- Unrecognized changes: assume other agent; focus your changes; stop + ask if conflicting.
- Leave breadcrumb notes in thread.

## Tools

### gh
- GitHub CLI for PRs/CI/releases.
- `gh pr view --json number,title,url`, `gh run list/view`, `gh issue view`.

### python / uv
- Check for `pyproject.toml`, `setup.py`, or `requirements.txt` before installing.
- Prefer `uv pip install` if `uv` is available.

### trash
- Move to Trash: `trash <path>`. Never `rm -rf`.

### delta
- Git pager with side-by-side diffs. Already in PATH via gitconfig.

### Screenshots
- Path: `$SCREENSHOTS_DIR`
- Always use the **latest** file: `ls -t $SCREENSHOTS_DIR | head -1`

## Language/Stack Notes
- Python AI/ML: validate venv activation before running scripts; keep `requirements.txt` or `pyproject.toml` in sync.
- RAG projects: PDFs parsed in batches; mind memory when testing locally.
- LLM projects: check model availability + rate limits before long runs; log token counts.
- CI Action: test with act or push to branch; don't merge without green CI.

## Model Preference
- Prefer latest capable models. OK: Anthropic claude-sonnet-4-6 / claude-opus-4-6.
- Avoid deprecated/old model IDs.

## Style
- Telegraph. Drop filler. Min tokens.
- Code comments only where logic isn't self-evident.
- No backwards-compat shims, no speculative abstractions, no extra error handling for impossible cases.
