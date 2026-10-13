# Release checklist

Run before tagging or publishing (plan T-1204). Tick each item in the release PR.

- [ ] **Gate G0 / provenance:** private-person project, no employer or client information
      (decision D7); nothing derived from any real engagement or organisation.
- [ ] **Quality gate green locally and in CI:** `ruff check`, `ruff format --check`,
      `mypy --strict`, `pytest --req-report` (with `opa` installed, `ARG_REQUIRE_OPA=1`),
      `check_traceability.py --strict`, `gen_conformance.py --check`,
      `export_schemas.py --check`.
- [ ] **Wording check:** `uv run python scripts/check_wording.py` is clean; README and
      `LIMITATIONS.md` still state unofficial / demo only / not certified / not regulatory
      guidance (constitution rule 5).
- [ ] **Fictional-data check:** grep the repo for institution, client, or person names that
      are not "Example Bank" and the fictional agents/reviewers; no real keys (`gitleaks` in CI).
- [ ] **Dependency audit:** `uv run pip-audit` clean; new dependencies health-checked
      (recent releases, maintainers, adoption).
- [ ] **No copied paper content:** docs paraphrase and cite by section name; diagrams are
      original.
- [ ] **Docs current:** `docs/conformance.md` regenerated, ADR index up to date,
      `docs/production-gaps.md` reviewed, `LIMITATIONS.md` accurate.
- [ ] **Container/compose** (if shipped in the release): built and run once by hand
      (they are not exercised in CI).
- [ ] **Licence file** present (Apache-2.0) and `pyproject.toml` metadata matches.
