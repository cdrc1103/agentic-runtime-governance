# Extending the reference implementation

> Unofficial reference implementation based on the SAFR white paper. Not regulatory guidance.

Every swappable mechanism is an abstract class whose docstring starts with `Condition:`. You
add behaviour by subclassing, registering under a name, and naming it in `runtime.yaml`.
Nothing in the core imports your class.

## The recipe

1. Pick the abstract class from the table in `docs/spec/reference-principles.md`
   (all live under `arg.core.ports`, plus `arg.adapters`, `arg.gateway`, `arg.service.auth`).
2. Subclass it. Read its `Condition:` docstring; that is the contract.
3. `@register(AbstractClass, "my-name")` (`arg.core.registry.register`).
4. Make sure the module is imported before `build_runtime` runs (import it from your own
   entry point, or add it to a copy of `arg/builtins.py`). Plug-in discovery through entry
   points is described but not built.
5. Reference it in `runtime.yaml`: `{type: my-name, ...constructor kwargs...}`.
6. Add a builder for your class to the shared contract suite
   (`tests/contracts/test_*_contract.py`) and run it: it is parametrised over every registered
   implementation, so a new class is held to the same behaviour as the reference ones.

Template methods (`AuditStore.append`, `StateStore.reserve`, `TokenService.redeem`,
`GatewayAdapter.handle`, `NativeAdapter.guard`) hold the invariants; do not override them.
You implement only the abstract hooks.

## Worked example 1: a custom control evaluator

`docs/examples/beneficiary_blocklist.py` (tested in `tests/test_extending_examples.py`):

```python
@register(ControlEvaluator, "blocklist")
class BeneficiaryBlocklistEvaluator(ControlEvaluator):
    def evaluate(self, control, context):
        blocked = control.logic.get("blocked", [])
        beneficiary = context.envelope.action.parameters.get("beneficiary")
        ...  # fire BLK_BENEFICIARY_BLOCKED, or BLK_BENEFICIARY_UNREADABLE (fail closed)
```

Use it from a control file in the bundle:

```yaml
control_id: sanctions-beneficiary-blocklist
version: 1
source: regulatory
category: custom
logic: {type: blocklist, blocked: [vendor-666]}
effect: deny
owner: compliance
review_status: approved
```

and name the evaluator in `runtime.yaml`: `evaluators: {blocklist: {type: blocklist}}`.
Rules for evaluators: pure function of `(control, context)`, no clock, no I/O, no randomness;
read only what `EvaluationContext` carries. If it raises, dispatch turns that into a Deny.

## Worked example 2: a custom audit store

`docs/examples/jsonl_audit_store.py` implements three methods (`read_stream`, `_read_head`,
`_persist`). Hash chaining, the expected-head check, `head()` and `verify()` come from the base
class, so an implementation cannot weaken them. Configure with
`audit_store: {type: jsonl, path: var/audit.jsonl}`.

## Things to keep in mind

* Config over code: thresholds, limits, reviewers and mandates belong in YAML, not subclasses.
* Keep `src/arg/core` free of web, cloud and framework imports.
* New behaviour needs a requirement ID first (`docs/spec/requirements.md`), tagged `[DESIGN]`
  if the paper is silent, and a test marked with it.
