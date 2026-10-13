# Deployment considerations

> Considerations only. This repo ships no provider-specific code or infrastructure-as-code, and
> asserts no provider limits. Verify everything against your platform's current documentation.

## Shape

* **Decision service** (`arg.service.main:create_app_from_env`): an ASGI app, stateless apart
  from its stores. Any container or serverless runtime that can host an ASGI app and reach the
  stores can run it.
* **Gateways** (`arg.gateway.main:create_app_from_env`): stateless ASGI proxies; scale
  horizontally behind any load balancer. They need only the decision service URL and a
  submit-role (standalone) or consume-role (hybrid) token.
* **State** lives behind `StateStore`, `AuditStore` and `AnchorSink`. SQLite and in-memory
  implementations are single-process; a shared deployment needs a networked implementation
  (not built; see `docs/production-gaps.md`).

## Serverless mapping (considerations)

| Concern | Consideration |
|---|---|
| Stateless compute | The service keeps no state between requests, so instances are interchangeable *if* the stores are shared. |
| External state | Move stores to a networked database; atomic counters and conditional writes on the stream head are the two required primitives (see the contract suites). |
| Sweeper | `POST /v1/escalations/sweep` is the timeout hook; call it from any scheduler at a period well below the shortest escalation timeout. |
| Anchoring | `POST /v1/audit/{agent}/anchor` from a scheduler, writing to a sink in a separate trust domain. |
| Cold starts | The decision path is on the critical path of every agent action; consider a minimum number of warm instances. Measure on your platform; this repo makes no latency claims. |
| Fail closed | A service that is down means actions are blocked (`INT-05`). Decide deliberately how much availability that is worth. |
| Config and secrets | `runtime.yaml` is non-secret; tokens and keys arrive through environment variables (`ARG_TOKENS`, `ARG_TOKEN_KEY`, ...). |

## Local container

`Dockerfile` and `compose.yaml` build and run the decision service with the sample
configuration (in-memory/SQLite stores) plus a small scheduled caller for the sweeper.
See `README.md`. They have not been exercised in CI.
