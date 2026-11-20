"""Words for the internal-agents demo: generic step texts, technology chips, scenario copy.

Only prose lives here. Every number, code and artifact on the page comes from the recorded
run. "Estate" lines are illustrative integration points, tagged [DESIGN]; they make no claim
about any institution's systems. Not regulatory guidance.
"""

DISPOSITION = {
    "deny": "Deny",
    "escalate": "Require human approval",
    "auto_execute": "Allow automatically",
    "observe": "Allow with monitoring",
}

# beat id -> (title, plain words, technical words)
GENERIC: dict[str, tuple[str, str, str]] = {
    "envelope": (
        "The action is wrapped in a signed envelope",
        "Before anything runs, the agent's platform writes the action down in a standard "
        "envelope: what, where, how much, the steps the agent took to get here, and who is "
        "asking. The agent's own key signs it, so it cannot be quietly changed on the way.",
        "Governance Envelope v1: a Pydantic model serialised to JSON, canonicalised "
        "(RFC 8785) and signed with the agent instance's Ed25519 key. A native adapter in "
        "the agent process builds it; a gateway can build the same envelope from an observed "
        "MCP or HTTP call instead.",
    ),
    "validate": (
        "Is the request complete and coherent?",
        "The control plane first checks the envelope is well-formed: the required fields for "
        "this kind of action are there, the agent named inside is the agent that sent it, and "
        "the recorded steps make sense.",
        "ValidateStage: schema check, required parameters per action type, trace "
        "completeness and ordering, mandate reference resolves. Failure is a decision (Deny), "
        "not an exception.",
    ),
    "identity": (
        "Who is acting?",
        "The agent is looked up in the bank's register of agents. The control plane checks it "
        "is active and that the signature matches the key registered for that agent. Unknown, "
        "suspended or forged means stop here.",
        "IdentityStage with DefaultIdentityVerifier: registry lookup, status check, network "
        "context, then the Ed25519 signature is verified against the registered public key "
        "(origin authentication).",
    ),
    "mandate": (
        "What is this agent allowed to do?",
        "Every agent works under a mandate: a written, signed permission slip from an "
        "accountable person. It says which actions are allowed, up to what size, and for how "
        "long. The control plane checks the slip is genuine and still valid.",
        "MandateStage with FileMandateResolver: the mandate is signed by the principal's key; "
        "signature, validity window, revocation and delegation depth are checked. Its limits "
        "are later used to narrow the policy limit.",
    ),
    "controls": (
        "Which controls apply?",
        "The bank's risk owners wrote the rules. The control plane picks those that apply to "
        "this kind of agent and this kind of action, and notes the exact version of the rulebook "
        "so the decision can be reproduced later.",
        "RetrieveStage with BundleControlsRepository: YAML controls filtered by action type and "
        "agent class. The policy version is the SHA-256 manifest of every file in the bundle. "
        "Running totals are read from the state store as a snapshot.",
    ),
    "evaluate": (
        "Each control gives its verdict",
        "Every applicable control looks at the action and answers pass or fire. A control that "
        "fires says what it wants: stop it, ask a human, or watch it. The inputs it used are "
        "recorded.",
        "Pure functions, one per control kind. Probabilistic inputs (agent confidence) arrive "
        "as signals computed outside the core. The same input always gives the same result.",
    ),
    "risk": (
        "How risky is this kind of action?",
        "Separately from the hard rules, each action type has a risk profile set in advance: "
        "how reversible it is, how much it matters, how sensitive it is. The score can, on its "
        "own, call for monitoring or a human.",
        "ConfigRiskCalibrator: ordinal ranks (0 to 2) for reversibility, materiality band, "
        "customer impact and regulatory sensitivity, plus one for novelty, summed and compared "
        "to the observe, escalate and deny thresholds in calibration.yaml.",
    ),
    "resolve": (
        "One decision comes out",
        "All verdicts are combined into exactly one disposition. If controls disagree the "
        "stricter one wins: Deny over human approval, over monitoring, over automatic.",
        "PrecedenceResolutionPolicy (Deny > Escalate > Observe > Auto-Execute). The reasons "
        "that decided the outcome are recorded as controlling; the others as contributing.",
    ),
    "audit": (
        "The decision is written to the audit log",
        "Whatever the outcome, a record is added: who, what, which rulebook version, which "
        "rules, what decision. Each record is chained to the one before it, so rewriting "
        "history would be noticed.",
        "DecisionService appends to the AuditStore (SQLite here). Entry hash = SHA-256 over "
        "the entry plus the previous hash. The chain head is published to an anchor sink "
        "outside the store and verified.",
    ),
}

TECH: dict[str, list[str]] = {
    "agent": ["Agent framework (any)", "Native adapter or MCP/HTTP gateway"],
    "envelope": ["Pydantic v2", "RFC 8785 canonical JSON", "SHA-256", "Ed25519"],
    "validate": ["Schema validation", "Required parameters per action", "Trace checks"],
    "identity": ["YAML agent register", "Ed25519 public keys", "active / suspended / revoked"],
    "mandate": ["Signed mandate (Ed25519)", "Validity window", "Revocation, delegation depth"],
    "controls": ["YAML control bundle", "Manifest hash = policy version", "Approved only"],
    "evaluate": ["Python evaluators", "Counter snapshot (SQLite)", "Optional OPA / Rego"],
    "risk": ["YAML calibration", "Ordinal score", "Thresholds per action type"],
    "resolve": ["Deterministic, no I/O", "Precedence rule"],
    "audit": ["SQLite append-only", "SHA-256 hash chain", "File anchor sink"],
    "token": ["JWS compact, EdDSA", "Bound to the exact action", "One-time id"],
    "escalation": ["Queue in SQLite state", "Reviewer directory (YAML)", "Authority limits"],
    "execute": ["FastAPI decision API", "POST /v1/tokens/consume", "Bearer role: consume"],
}

# Illustrative integration points [DESIGN]; not a statement about any institution's stack.
ESTATE = {
    "identity": "Could be fed from the bank's identity and access management or workload identity.",
    "mandate": "Could be issued from the bank's delegation-of-authority matrix.",
    "controls": "Authored by risk owners, versioned like code, released through change management.",
    "escalation": "Could appear in the bank's existing approval workflow for reviewers.",
    "audit": "Stream can be exported to the bank's monitoring and archive systems.",
    "execute": "The ERP, billing or ledger verifies the token at its own API edge.",
}

# scenario id -> copy. `system` is the bank system the action targets.
SCENARIOS: dict[str, dict[str, str]] = {
    "p2p-invoice": {
        "domain": "P2P",
        "title": "Approve a matched supplier invoice",
        "blurb": "Procure-to-pay. Small, fully matched, inside every limit.",
        "system": "Accounts payable (ERP)",
        "intent": "An invoice agent has matched invoice INV-20417 to its purchase order and goods "
        "receipt and wants to approve it for 8,400.",
        "evaluate": "Every control passes: the agent may approve invoices, it is confident, both "
        "matches are in its recorded steps, and 8,400 is under its limit.",
        "resolve": "No control objected and risk is low. The action is allowed automatically.",
    },
    "p2p-payment": {
        "domain": "P2P",
        "title": "Release a supplier payment above the agent's limit",
        "blurb": "Procure-to-pay. Over the mandate limit, so a person decides.",
        "system": "Payments (ERP to bank rail)",
        "intent": "A payment agent wants to release 32,000 to a supplier for a matched invoice.",
        "evaluate": "The policy ceiling is 50,000, but this agent's mandate only grants 25,000. "
        "The control takes the smaller of the two, so 32,000 is over the limit.",
        "resolve": "Going over a limit is not forbidden. It needs a person. The payment is held "
        "and nothing executes yet.",
    },
    "p2p-bank-change": {
        "domain": "P2P",
        "title": "Change a supplier's bank details after an email",
        "blurb": "Procure-to-pay. An action no payment agent is allowed to take.",
        "system": "Supplier master data (ERP)",
        "intent": "An inbound email asks to change a supplier's account. The payment agent drafts "
        "the update and tries to apply it.",
        "evaluate": "The authorisation control for payment-side agents does not list this kind of "
        "action at all, and neither does the agent's mandate. It fires, and Deny is its effect.",
        "resolve": "Denied. Even if the control had allowed it, the risk score would have "
        "asked for a human. That is defence in depth.",
    },
    "o2c-billing": {
        "domain": "O2C",
        "title": "Issue a fee invoice",
        "blurb": "Order-to-cash. Routine billing in policy.",
        "system": "Billing and receivables",
        "intent": "A billing agent raises a 1,250 account fee invoice according to the fee schedule.",
        "evaluate": "Allowed action, under the per-invoice limit, and well under the hourly "
        "rate cap. The rate control counts how many invoices this agent has raised.",
        "resolve": "Nothing objects. Allowed automatically.",
    },
    "o2c-writeoff": {
        "domain": "O2C",
        "title": "Write off receivables, with a daily total",
        "blurb": "Order-to-cash. Each write-off is small. The running total is not.",
        "system": "Receivables ledger",
        "intent": "A collections agent writes off three small receivables in one day: 1,800, then "
        "2,000, then 1,500.",
        "evaluate": "Each amount is under the per-write-off limit. But the daily cap is 5,000 "
        "in total, and the control keeps a running count.",
        "resolve": "The first two are allowed with monitoring. The third would take the day to "
        "5,300, so it is held for a person.",
    },
    "r2r-journal": {
        "domain": "R2R",
        "title": "Post a routine reconciliation journal",
        "blurb": "Record-to-report. Allowed, but watched.",
        "system": "General ledger",
        "intent": "A reconciliation agent posts a 48,000 journal that clears matched bank "
        "statement items.",
        "evaluate": "Everything is within policy. No hard rule fires.",
        "resolve": "Posting to the ledger changes reported numbers, so the risk profile asks "
        "for monitoring. The action runs, and an observation is recorded for follow-up.",
    },
    "r2r-closed-period": {
        "domain": "R2R",
        "title": "Post to a closed accounting period",
        "blurb": "Record-to-report. A boundary the agent must not cross.",
        "system": "General ledger",
        "intent": "The reconciliation agent finds a difference in December and tries to post a "
        "correction into the closed period.",
        "evaluate": "The integration classifies this posting as its own kind of action, which the "
        "authorisation control does not permit. Finer rules (a specific ledger account, say) "
        "would need a custom or Rego evaluator.",
        "resolve": "Denied. The ledger never sees the request.",
    },
    "r2r-adjustment": {
        "domain": "R2R",
        "title": "Manual adjustment from an unsure agent",
        "blurb": "Record-to-report. Low confidence means a person looks.",
        "system": "General ledger",
        "intent": "The agent proposes a 12,000 manual adjustment. It reports 0.55 confidence and "
        "has not attached a supporting document.",
        "evaluate": "The amount is fine. The evidence control wants at least 0.8 confidence "
        "and a supporting document. The agent is unsure, so it fires.",
        "resolve": "Held for the financial controller. The agent's doubt is itself a reason "
        "for a human to look.",
    },
    "kill-switch": {
        "domain": "All",
        "title": "Kill switch and control-plane outage",
        "blurb": "Suspend an agent in one place. If the control plane fails, nothing runs.",
        "system": "Billing and receivables",
        "intent": "A billing agent is working normally. Then the bank suspends it. Later, the "
        "control plane itself loses a dependency.",
        "evaluate": "Not reached once the agent is suspended.",
        "resolve": "Denied. The system fails closed: if it cannot show that an action is "
        "allowed, nothing runs.",
    },
}

# ---- presentation layer: a few words per step -------------------------------------

# One illustrative enterprise tool per step. Examples of what could implement the step in a
# large organisation; no statement about any institution's stack, no endorsement [DESIGN].
TOOLS = {
    "propose": "LangGraph",
    "identity": "Microsoft Entra ID",
    "controls": "Open Policy Agent",
    "decide": "Kong Gateway",
    "evidence": "Splunk",
    "system": "SAP S/4HANA",
    "review": "ServiceNow",
}

VERB = {
    "invoice.approve": "Approve invoice",
    "supplier_payment.release": "Release supplier payment",
    "supplier.bank_details.change": "Change supplier bank details",
    "fee_invoice.issue": "Issue fee invoice",
    "receivable.write_off": "Write off receivable",
    "journal.post": "Post journal",
    "journal.adjust": "Post manual adjustment",
    "journal.post_closed_period": "Post to a closed period",
}

AGENT_NAME = {
    "p2p-invoice-agent-1": "Invoice agent",
    "p2p-payment-agent-1": "Payment agent",
    "o2c-billing-agent-1": "Billing agent",
    "o2c-collections-agent-1": "Collections agent",
    "r2r-recon-agent-1": "Reconciliation agent",
}

LEAD = {
    "p2p-invoice": "Matched to its purchase order and goods receipt.",
    "p2p-payment": "A matched invoice is ready to pay.",
    "p2p-bank-change": "An inbound email asked for new bank details.",
    "o2c-billing": "A routine account fee.",
    "o2c-writeoff": "Small write-offs, one after another.",
    "r2r-journal": "Clears matched bank statement items.",
    "r2r-closed-period": "A December difference, but December is closed.",
    "r2r-adjustment": "The agent is unsure and attached no document.",
    "kill-switch": "A routine fee invoice.",
}

CONTROL_LABEL = {
    "auth-p2p": "Action allowed for this agent",
    "auth-o2c": "Action allowed for this agent",
    "auth-r2r": "Action allowed for this agent",
    "evidence-p2p-three-way-match": "Evidence and confidence",
    "evidence-r2r-adjustment": "Evidence and confidence",
    "exposure-p2p-per-action": "Amount within limit",
    "exposure-o2c-invoice-per-action": "Amount within limit",
    "exposure-o2c-writeoff-per-action": "Amount within limit",
    "exposure-o2c-writeoff-daily": "Daily total within cap",
    "exposure-r2r-journal-per-action": "Amount within limit",
    "rate-o2c-billing": "Not acting too often",
}

REASON = {
    "EXP_PER_ACTION_EXCEEDED": "Over the limit",
    "EXP_AGGREGATE_EXCEEDED": "Daily total would pass the cap",
    "AUTH_ACTION_TYPE_NOT_PERMITTED": "Not an action this agent may take",
    "AUTH_ACTION_NOT_IN_MANDATE": "Not in the agent's mandate",
    "EVD_CONFIDENCE_BELOW": "Agent is not confident enough",
    "EVD_REQUIRED_MISSING": "Supporting evidence is missing",
    "RATE_EXCEEDED": "Acting too often",
    "IDN_AGENT_SUSPENDED": "Agent is suspended",
    "IDN_AGENT_REVOKED": "Agent is revoked",
    "IDN_AGENT_UNKNOWN": "Unknown agent",
    "IDN_SIGNATURE_INVALID": "Signature does not match",
    "SYSTEM_ERROR": "Control plane error: fail closed",
    "RISK_OBSERVE_THRESHOLD": "Sensitive action: watched",
}
