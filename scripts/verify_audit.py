"""Verify an exported audit JSONL file offline (AUD-06).

Usage: ``verify_audit.py entries.jsonl [anchors.jsonl]``. Exit code 0 iff every stream in the
file verifies (and matches its latest anchor, if an anchors file is given).
"""

import json
import sys
from collections import defaultdict

from arg.core.audit.anchor import FileAnchorSink, load_jsonl
from arg.core.audit.chain import verify_entries
from arg.core.models import AuditEntry


def main(argv: list[str]) -> int:
    """CLI entry point."""
    if not argv:
        print(__doc__)
        return 2
    streams: dict[str, list[AuditEntry]] = defaultdict(list)
    for e in load_jsonl(argv[0]):
        streams[e.agent_stream].append(e)
    sink = FileAnchorSink(argv[1]) if len(argv) > 1 else None
    bad = 0
    for name, entries in sorted(streams.items()):
        entries.sort(key=lambda e: e.seq)
        result = verify_entries(entries, name, sink.latest(name) if sink else None)
        print(json.dumps({"stream": name, **result.model_dump()}))
        bad += not result.ok
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
