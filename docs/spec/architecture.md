# Architecture

> Unofficial reference implementation based on the SAFR white paper. Not regulatory guidance.

## Architecture

**Principle:** one decision core, several enforcement points. Native and gateway differ only in where the envelope is built and where the outcome is enforced.

```mermaid
flowchart LR
  subgraph Agent process
    A[Agent / framework] --> N[Native adapter]
  end
  N -- envelope --> C
  A -- tool call + token --> G[Gateway adapter]
  G -- envelope (standalone mode) --> C
  subgraph Core [SAFR core]
    C[Decision service] --> I[Agent identity] --> R[Controls repository] --> D[Disposition engine] --> L[Audit log]
    C --- S[(State store)]
  end
  G -- token verified --> U[Upstream tool / rail]
```

| Layer | Contents | Runs as |
|---|---|---|
| `arg.core` | Models, canonicalisation, crypto, identity, controls, engine, audit, escalation, tokens, store/registry/sink interfaces | Library, no web or cloud dependencies |
| `arg.service` | Decision API (FastAPI), config, telemetry | Container; serverless-compatible |
| `arg.adapters.*` | Native hooks: embedded mode (in-process core) or HTTP mode | In the agent process |
| `arg.gateway.*` | MCP gateway and HTTP egress gateway | Separate stateless process |
| `demo/` | Example Bank mock rails, scripted agents, scenario runner | Local and CI |

**Tradeoff to document:** a gateway sees the real call (authentic action, credential-derived identity) but not the reasoning, so the trace is thin. Native sees a rich trace but it is agent-declared. Hybrid mode (INT-04) combines them.

**Gateway modes**
- **Standalone:** gateway builds the envelope from the observed call and decides. Satisfies INT-02 alone.
- **Hybrid:** gateway requires a valid decision token whose action hash matches the observed call, then forwards. Bypass of native instrumentation is blocked.

**Escalation is asynchronous.** `Escalate` returns `pending` with an `escalation_id`; connections are never held open. Reviewer approval issues a token; the agent retries with it. A sweeper (callable by a scheduled function) applies the timeout default: block, or reassign to a senior reviewer.

**State:** the core is stateless; all state (exposure/rate counters, escalations, consumed token IDs, audit streams) sits behind interfaces. Implementations: in-memory, SQLite (local), and Postgres (portable networked store). A shared contract test suite runs against every implementation.

**Telemetry:** OpenTelemetry spans per pipeline stage, metrics (decisions by outcome, stage latency, escalation queue depth). For the envelope's action trace, map to the OpenTelemetry GenAI conventions (`invoke_agent`, `execute_tool`). Check their current status and pin a version; at time of writing they were reported as "Development".

---

## As built

The diagrams below are original to this repository (Mermaid) and describe the implementation
as it stands, which differs from the plan in a few places (noted under each).

### Components and integration patterns

```mermaid
flowchart LR
  subgraph AgentProcess[Agent process]
    AG[Agent code] --> NA[NativeAdapter<br/>build_envelope / enforce]
  end
  NA -- "envelope (signed)" --> CL{GovernanceClient<br/>embedded or HTTP}
  AG -. "tool call + token" .-> GW[Gateway<br/>MCP or HTTP egress]
  GW -- "envelope from observed call<br/>(standalone)" --> CL
  GW -- "token redeem<br/>(hybrid)" --> TK[/tokens/consume/]
  CL --> DS
  subgraph Core[Decision core]
    DS[DecisionService] --> P[Pipeline stages]
    DS --- ST[(StateStore)]
    DS --- AU[(AuditStore + AnchorSink)]
    DS --- EQ[EscalationQueue]
    TS[TokenService]
  end
  DS --> TS
  GW -- "allowed call" --> UP[Upstream tool / rail]
  RV[Reviewer] -- resolution --> DS
```

### Decision pipeline

```mermaid
flowchart TD
  A[raw envelope JSON] --> B{idempotent?<br/>envelope_id seen}
  B -- yes --> R[return original decision]
  B -- no --> V[validate: schema, completeness, coherence]
  V --> I[identity: registry, status, context, origin authentication]
  I --> M[mandate: validity, signature, revocation, depth]
  M --> C[retrieve controls + counter snapshot]
  C --> E[evaluate: evaluators, risk calibration, precedence]
  E --> X{outcome}
  X -- Auto-Execute / Observe --> S[reserve counters] --> T[issue token]
  X -- Escalate --> Q[open escalation, cap check]
  X -- Deny --> D
  T --> D[audit append, hash chain]
  Q --> D
  V -. reject .-> D
  I -. reject .-> D
  M -. reject .-> D
  D --> O[response]
```

Every rejection and every outcome ends in the audit append (AUD-01). Any exception anywhere
becomes Deny (INT-05); if the append itself fails after reserving, the reservation is
released (SG-04).

### Escalation states

```mermaid
stateDiagram-v2
  [*] --> PENDING: Escalate (queue below cap)
  PENDING --> APPROVED: reviewer approves (token issued)
  PENDING --> DECLINED: reviewer declines
  PENDING --> MODIFIED: reviewer modifies (child envelope re-enters)
  PENDING --> PENDING: timeout, on_timeout=senior (once)
  PENDING --> TIMED_OUT: timeout, blocked
```

Differences from the plan: audit is performed by `DecisionService` on every path rather than
as a configurable last stage (ADR-0014); a `mandate` stage was added; framework adapters are a
docking point (`docs/adapters/README.md`) rather than shipped implementations.
