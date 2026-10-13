"""Shared type aliases for the abstract contracts.

Phase 0 uses ``JsonObject`` for payloads. Phases 1-5 replace these with the pydantic
models of ``docs/spec/contracts.md`` (Envelope, Mandate, Control, ...).
"""

from collections.abc import Mapping

JsonObject = Mapping[str, object]
