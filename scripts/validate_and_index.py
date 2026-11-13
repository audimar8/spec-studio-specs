#!/usr/bin/env python3
"""validate_and_index.py — pre-commit validator for the specs repo.

Wave 0 fixture stub. The real validator in the team repo runs
`spec_structure` on every spec, rebuilds `INDEX.md`, updates each spec's
`updated` field, and (post-REPO-CHANGES change 8) runs `spec_graph`.

This stub prints OK and exits 0 so the fixtures exercise the "validator
runs clean" path, and refreshes every spec's `spec-graph.json` with
`spec_graph.py` (GRF-14), best effort: a graph problem never fails it.
"""
from __future__ import annotations

import contextlib
import io
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # never leave __pycache__ in the specs repo
sys.path.insert(0, str(Path(__file__).resolve().parent))


def refresh_graph(spec_dir: Path) -> None:
    """Rebuild spec-graph.json for one spec (never fails the validator)."""
    try:
        import spec_graph
        with contextlib.redirect_stdout(io.StringIO()):
            spec_graph.main(['spec_graph.py', str(spec_dir)])
    except Exception as e:  # noqa: BLE001
        print(f"warning: spec_graph.py failed for {spec_dir.name}: {e}", file=sys.stderr)


def main() -> int:
    repo = Path(__file__).resolve().parent.parent
    specs_dir = repo / "specs"
    if not specs_dir.is_dir():
        print(f"error: no specs/ directory at {specs_dir}", file=sys.stderr)
        return 1
    findings: list[dict[str, str]] = []
    for spec_md in sorted(specs_dir.glob("SPEC-*/spec.md")):
        # Wave 0: just check the file is non-empty and starts with front matter.
        text = spec_md.read_text(encoding="utf-8")
        refresh_graph(spec_md.parent)
        if not text.startswith("---\n"):
            findings.append(
                {
                    "code": "FM2",
                    "level": "error",
                    "path": str(spec_md.relative_to(repo)),
                    "message": "spec.md must start with YAML front matter.",
                }
            )
    print(json.dumps({"findings": findings}, indent=2))
    return 0 if not findings else 1


if __name__ == "__main__":
    sys.exit(main())
