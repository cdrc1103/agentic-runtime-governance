# Reference principles and extension architecture

> Unofficial reference implementation based on the SAFR white paper. Not regulatory guidance.

## Reference-implementation principles and extension architecture

**Intent.** This repository is a *reference implementation*: a readable, traceable example of how the SAFR conditions can be satisfied, built so that any part can be swapped. It is not a ready-to-use product. The paper itself presents each SAFR mechanism as a condition that should hold for every proposed action and leaves the form of implementation to the deployment context. The abstract base classes below encode those conditions; the built-in classes are one example of satisfying them.

| Prioritise | Deprioritise |
|---|---|
| Clarity, small modules, docstrings citing requirement IDs | Throughput and latency tuning |
| Traceability: paper statement → requirement → abstract class → test | Feature breadth |
| Swappability, proven by contract tests | Operational hardening |
| Honest documentation of limits | UI and ops tooling |

### Extension points (abstract base classes)

| Abstract class | Condition it encodes | Reference implementations | Requirements |
|---|---|---|---|
| `AgentRegistry` | Resolve a claimed agent to a registry entry, or to nothing | `FileRegistry`, `CompositeRegistry` (open-network authority selection) | IDN-01/03/04 |
| `IdentityVerifier` | Bind the action to a registered agent before anything else; otherwise reject and report | `DefaultIdentityVerifier` | IDN-01/02/05 |
| `EnvelopeAuthenticator` | Establish the origin of an envelope | `AdapterSignatureAuthenticator` (native), `GatewayObservedAuthenticator` (gateway) | ENV-04 |
| `ControlsRepository` | Return the controls that apply to an identity and action | `BundleControlsRepository` (files) | CTL-01/07 |
| `MandateResolver` | Resolve and validate a mandate (validity, signature, revocation, depth) | `FileMandateResolver` | CTL-03/04 |
| `ControlEvaluator` | Evaluate one control kind deterministically; return findings | `AuthorisationEvaluator`, `ExposureEvaluator`, `RateEvaluator`, `EvidenceEvaluator`, `RegoControlEvaluator` (optional) | CTL-02/05, DSP-01 |
| `RiskCalibrator` | Map action and signals to a risk profile from design-time parameters | `ConfigRiskCalibrator` | DSP-03/04 |
| `ResolutionPolicy` | Combine findings into exactly one outcome | `PrecedenceResolutionPolicy` | DSP-02/06 |
| `StateStore` | Atomic reserve, consume, and escalation state | `InMemoryStateStore`, `SqliteStateStore`, `PostgresStateStore` (optional) | SG-04, INT-04, ESC |
| `AuditStore` | Append-only, tamper-evident persistence | in-memory, SQLite, Postgres (optional) | AUD-01..06 |
| `AnchorSink` | Export the chain head outside the store | `FileAnchorSink` | AUD-06 |
| `TokenService` | Issue and verify decision tokens | `Ed25519TokenService` | INT-04 |
| `EscalationQueue` | Hold pending reviews; look up reviewer authority | state-store-backed queue, file-based reviewer directory | ESC-01..06 |
| `Authenticator` | Authenticate API callers into a principal with roles | `BearerTokenAuthenticator`, `UnsafeNoAuthenticator` (tests only) | D5 |
| `NativeAdapter` | Build an envelope from a framework event and enforce the outcome | One subclass per framework, plus a generic wrapper | INT-01 |
| `GatewayAdapter` | Intercept a call, build the envelope from the observed call, enforce the outcome | `McpGateway`, `HttpEgressGateway` | INT-02 |
| `PipelineStage` | One step of the paper's action lifecycle | `ValidateStage`, `IdentityStage`, `RetrieveStage`, `EvaluateStage`, `ReserveStage`, `AuditStage` | Action Lifecycle, DSP-05 |

### Factory and registry pattern
- Each abstract class has a `ComponentRegistry` mapping a name to a class. Implementations register with a decorator, e.g. `@register(AuditStore, "sqlite")`.
- A `ComponentFactory` builds an instance from a config block such as `{type: sqlite, path: ...}`.
- **Composition root:** `arg.runtime.build_runtime(config) -> GovernanceRuntime` is the only place that wires components together, driven by `runtime.yaml`. No other module imports a concrete implementation.
- Dependencies are injected through constructors. No module-level singletons or global state.
- The decision pipeline is an ordered list of `PipelineStage` objects built by the factory from config, mirroring the paper's lifecycle (draw our own diagram).
- Third-party plug-in discovery through Python entry points: document it, do not build more than a stub.

### Design rules
1. Use `abc.ABC` and `@abstractmethod`. Each class docstring starts with `Condition:`, the condition in our own words plus requirement IDs.
2. **Template method** where an invariant must not be skippable. Example: `AuditStore.append()` is concrete in the base class (computes the hash chain, checks the expected head) and calls abstract `_persist()` and `_read_head()`, so an implementer cannot bypass the chain. Same idea for input validation in `StateStore.reserve()`.
3. An abstract class exists only where the paper or this plan names a swappable mechanism. One level of inheritance; prefer composition. No speculative abstractions.
4. **Two-implementation rule:** each abstract class ships with one reference implementation and, where cheap, a second implementation or test double, so the contract is shown to be implementation-independent.
5. **Contract suites:** `tests/contracts/<abstract_class>_contract.py`, parametrised over every registered implementation. Anyone adding an implementation runs the suite against it.
6. Choose the simplest code that satisfies the condition. Comments explain why, with a requirement ID.
7. Configuration over code: whatever a risk or compliance owner would change (controls, calibration, reviewers, mandates) lives in YAML, not Python.

### Not part of "reference grade" (document, do not build)
High availability, horizontal scaling, performance tuning, key management and rotation, multi-tenancy, database migrations, secrets management, API rate limiting, parsing hardening beyond schema validation, UI, SLAs and runbooks. Write them once, honestly, in `docs/production-gaps.md` as "what a production deployment would additionally need".

### Deliverables that serve the reference purpose
- `docs/extending.md`: how to implement your own component, with one worked example (a custom `ControlEvaluator` and a custom `AuditStore`).
- `docs/production-gaps.md`.
- The conformance matrix extended with requirement → abstract class → test.

---
