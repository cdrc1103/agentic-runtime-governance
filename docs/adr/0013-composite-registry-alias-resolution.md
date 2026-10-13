# ADR-0013: Composite registry follows aliases to the authoritative registry

- Status: accepted (default decision)
- Tag: [DESIGN]. IDN-04 says the authoritative registry is determined per context; the
  mechanism is ours.

## Decision

`CompositeRegistry` maps network context to a registry name. A claim is looked up in the
authoritative registry first. If absent, other registries are consulted only for an
`aliases[<authoritative registry name>]` pointer, which is then resolved in the authoritative
registry. Status, keys and principal always come from the authoritative registry.

## Consequences

A non-authoritative registry can only point, never vouch. Aliases are configuration owned by
the registry operator.
