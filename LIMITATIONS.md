# Limitations

This project is an **unofficial, independent reference implementation** based on the white
paper *Safeguards for Agentic Finance at Runtime* (SAFR). It is:

* **Demo only.** Not production-grade, not hardened, not load-tested.
* **Not certified** and not a statement of compliance with anything. Passing the conformance
  suite here shows that each requirement and scenario of *this repository's* specification has
  a test, nothing more.
* **Not regulatory guidance.** The paper itself does not constitute regulatory guidance or
  supervisory expectations, and neither does this code. It is not affiliated with or endorsed by
  MAS, BuildFin.ai, or any contributor to the paper.
* **Fictional.** "Example Bank", its agents, principals, controls, thresholds and reviewers are
  invented and illustrative.
* **Partial by choice.** No framework-specific agent adapters are shipped; there is a tested
  docking point. No Postgres stores, no UI, no key management.

Read `docs/production-gaps.md` for what a real deployment would additionally need, and
`docs/spec/spec-gaps.md` for the places where this repository makes its own decisions where the
paper is silent (each tagged `[DESIGN]`).
