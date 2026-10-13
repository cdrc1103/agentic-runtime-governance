# ADR-0012: Risk calibration as an additive ordinal score

- Status: accepted (default decision, owner may revise at a checkpoint)
- Tag: [DESIGN]. The paper names the calibration factors (DSP-03) but not how they combine.

## Decision

Per action type, `calibration.yaml` assigns ordinal levels (reversibility, customer impact,
regulatory sensitivity), materiality bands over a named parameter, and an optional novelty
rule over a signal. Risk score = sum of ranks (0..2 each) + 1 if novel. Three thresholds per
action type (`observe_at <= escalate_at <= deny_at`) map the score to the outcome the risk
alone indicates. That outcome is combined with control findings by the DSP-06 precedence.

## Consequences

Monotone by construction (raising any factor never lowers the score), which is what the
Hypothesis property test checks. Coarse by design: a production institution would likely
calibrate richer models; the `RiskCalibrator` port is where that plugs in. An action type
without calibration is indicated Deny (fail closed). The file needs `review_status:
approved` in production mode (DSP-04).
