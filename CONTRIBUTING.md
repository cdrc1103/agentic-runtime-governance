# Contributing

Read `CLAUDE.md` (project constitution) first. In short:

1. **Spec first.** Behaviour needs a requirement ID in `docs/spec/requirements.md`, tagged
   `[PAPER]` (stated or directly implied by SAFR) or `[DESIGN]` (our decision). Record paper
   silences in `docs/spec/spec-gaps.md` with an ADR.
2. **Tests carry requirement IDs** (`@pytest.mark.req("ENV-01")`, `@pytest.mark.scenario("S01")`).
3. **Fail closed, deterministic core, ports and adapters.** New swappable mechanisms are
   abstract classes with a `Condition:` docstring, a contract suite, and factory registration
   (`docs/extending.md`).
4. **Fictional data only; paraphrase, never copy** the paper (it is © MAS).
5. **Wording:** "based on" / "implements the SAFR reference model". Never claim compliance, certification, or status as an authority (`scripts/check_wording.py` enforces this).
6. Gate before a PR: `uv run ruff check . && uv run ruff format --check . && uv run mypy &&
   uv run pytest --req-report && uv run python scripts/check_traceability.py --strict &&
   uv run python scripts/gen_conformance.py --check && uv run python scripts/check_wording.py`.
7. Conventional Commits (`feat|fix|refactor|build|ci|chore|docs|style|perf|test`).

`uv` is the only dependency manager.
