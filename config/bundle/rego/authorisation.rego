# Mirrors the built-in `authorisation` evaluator, except the mandate validity window
# (the mandate resolver already enforces it; see docs/adr for the Rego parity scope).
package arg.authorisation

violation := "AUTH_ACTION_TYPE_NOT_PERMITTED" if {
	count(input.logic.permitted_action_types) > 0
	not input.envelope.action.type in input.logic.permitted_action_types
} else := "AUTH_MANDATE_MISSING" if {
	input.mandate == null
} else := "AUTH_ACTION_NOT_IN_MANDATE" if {
	not input.envelope.action.type in input.mandate.permitted_actions
} else := "AUTH_MANDATE_AGENT_MISMATCH" if {
	input.mandate.agent_id != input.identity.agent_id
} else := "AUTH_PRINCIPAL_MISMATCH" if {
	input.mandate.principal != input.identity.principal
} else := "AUTH_DELEGATION_DEPTH_EXCEEDED" if {
	input.mandate.depth > input.logic.max_delegation_depth
}

result := {"effect": input.effect, "reason_codes": [violation]}
