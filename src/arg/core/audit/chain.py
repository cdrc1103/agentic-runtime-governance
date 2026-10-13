"""Hash chain and verification (AUD-02, AUD-06). Pure functions, usable offline."""

from collections.abc import Sequence

from arg.core.canonical import canonical_bytes, sha256_hex
from arg.core.models import Anchor, AuditEntry, VerifyResult
from arg.core.models.audit import GENESIS_HASH

__all__ = ["GENESIS_HASH", "compute_entry_hash", "verify_entries"]


def compute_entry_hash(entry: AuditEntry) -> str:
    """``SHA-256(prev_hash || canonical(entry without entry_hash))``, hex."""
    body = entry.model_dump(mode="json", exclude={"entry_hash"})
    return sha256_hex(entry.prev_hash.encode() + canonical_bytes(body))


def verify_entries(
    entries: Sequence[AuditEntry], agent_stream: str, anchor: Anchor | None = None
) -> VerifyResult:
    """Check sequence, links, hashes, and the anchor; report the first problem found."""
    prev = GENESIS_HASH
    for index, e in enumerate(entries, start=1):
        if e.agent_stream != agent_stream:
            return VerifyResult(ok=False, checked=index - 1, code="AUD_STREAM_MISMATCH", seq=e.seq)
        if e.seq != index:
            return VerifyResult(ok=False, checked=index - 1, code="AUD_SEQ_GAP", seq=e.seq)
        if e.prev_hash != prev:
            return VerifyResult(ok=False, checked=index - 1, code="AUD_CHAIN_BROKEN", seq=e.seq)
        if compute_entry_hash(e) != e.entry_hash:
            return VerifyResult(ok=False, checked=index - 1, code="AUD_ENTRY_MODIFIED", seq=e.seq)
        prev = e.entry_hash
    if anchor is not None and (
        len(entries) < anchor.seq or entries[anchor.seq - 1].entry_hash != anchor.entry_hash
    ):
        return VerifyResult(
            ok=False, checked=len(entries), code="AUD_ANCHOR_MISMATCH", seq=anchor.seq
        )
    return VerifyResult(ok=True, checked=len(entries))
