# Per-action exposure; mirrors the built-in `exposure` evaluator (scope: per_action).
# Input: envelope, identity, mandate, state, signals, at, logic (control.logic), effect.
package arg.exposure

amount := input.envelope.action.parameters[input.logic.amount_parameter]

result := {"effect": input.effect, "reason_codes": ["EXP_AMOUNT_UNREADABLE"]} if {
	not is_number(amount)
}

result := {"effect": input.effect, "reason_codes": ["EXP_PER_ACTION_EXCEEDED"]} if {
	is_number(amount)
	amount > input.logic.limit
}
