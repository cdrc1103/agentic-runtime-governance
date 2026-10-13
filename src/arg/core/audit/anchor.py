"""Head anchors written outside the audit store (AUD-06) and JSONL export."""

import json
from collections.abc import Iterable
from pathlib import Path

from arg.core.models import Anchor, AuditEntry, VerifyResult
from arg.core.ports import AnchorSink, AuditStore
from arg.core.registry import register


@register(AnchorSink, "file")
class FileAnchorSink(AnchorSink):
    """Append-only JSONL file of anchors; in production this is another trust domain."""

    def __init__(self, path: str | Path) -> None:
        """Use ``path``; parent directories are created on first publish."""
        self.path = Path(path)

    def publish(self, anchor: Anchor) -> None:
        """Append the anchor as one JSON line."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as fh:
            fh.write(anchor.model_dump_json() + "\n")

    def latest(self, agent_stream: str) -> Anchor | None:
        """Return the highest-seq anchor recorded for the stream."""
        if not self.path.exists():
            return None
        best: Anchor | None = None
        for line in self.path.read_text().splitlines():
            a = Anchor(**json.loads(line))
            if a.agent_stream == agent_stream and (best is None or a.seq > best.seq):
                best = a
        return best


def anchor_head(store: AuditStore, sink: AnchorSink, agent_stream: str) -> Anchor | None:
    """Publish the stream's current head (call periodically); None if the stream is empty."""
    head = store.head(agent_stream)
    if head is None:
        return None
    anchor = Anchor(agent_stream=agent_stream, seq=head.seq, entry_hash=head.entry_hash)
    sink.publish(anchor)
    return anchor


def verify_with_sink(store: AuditStore, sink: AnchorSink, agent_stream: str) -> VerifyResult:
    """Verify a stream against the latest externally anchored head."""
    return store.verify(agent_stream, sink.latest(agent_stream))


def export_jsonl(entries: Iterable[AuditEntry], path: str | Path) -> int:
    """Write entries one JSON object per line (AUD-05); return the count."""
    n = 0
    with Path(path).open("w") as fh:
        for e in entries:
            fh.write(e.model_dump_json() + "\n")
            n += 1
    return n


def load_jsonl(path: str | Path) -> list[AuditEntry]:
    """Read entries exported by ``export_jsonl``."""
    return [AuditEntry.model_validate_json(x) for x in Path(path).read_text().splitlines() if x]
