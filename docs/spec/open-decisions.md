# Owner decisions and source reference

> Unofficial reference implementation based on the SAFR white paper. Not regulatory guidance.

## Open decisions for the owner

| ID | Decision | Default if not answered |
|---|---|---|
| D1 | Licence | **Decided:** Apache-2.0 |
| D2 | First cloud target | **Decided:** none; reference only (see phase 11) |
| D3 | Repository name that does not imply official status | **Decided:** repo and distribution `agentic-runtime-governance`, import package `arg`. SAFR is mentioned only as "unofficial reference implementation of the SAFR white paper" in description and README. GitHub/PyPI availability not yet checked |
| D4 | Add an OPA/Rego control evaluator as a plugin | **Decided:** yes, light integration as an optional extra (task T-405) |
| D5 | Decision-API service authentication | **Decided:** role-scoped bearer tokens behind an `Authenticator` abstract class; mTLS and OIDC documented only (task T-606) |
| D6 | Post spec-gap issues to the BuildFin.ai working group | **Decided:** no |
| D7 | Employer/IP clearance (gate G0) | **Decided:** private-person project, no client or employer information |

---

## Source reference

*Safeguards for Agentic Finance at Runtime*, white paper v1.0, July 2026, Monetary Authority of Singapore / BuildFin.ai. Sections used: The SAFR Framework (Governance Envelope, Agent Identity, Controls Repository, Disposition Engine, Audit Log, Action Lifecycle); SAFR and Broader Ecosystem; How Institutions Implement SAFR (Integration patterns, Controls Configurations, Activating Human Reviewer Escalation). The paper states it does not constitute regulatory guidance or supervisory expectations.
