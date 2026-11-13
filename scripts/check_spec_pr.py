#!/usr/bin/env python3
"""Pull request checks for specs (GIT-24), run by GitHub Actions beside
validate_and_index.py.

Usage: check_spec_pr.py <base-ref> [<head-ref>]

Blocks a pull request that:
  - touches more than one spec folder (a draft changes only its own spec);
  - adds a spec whose number another folder already has, on the base branch
    or in the pull request itself;
  - adds a spec whose front matter id does not match its folder, or still
    carries a DRAFT- id.

Exit code 1 with one line per problem; 0 when the pull request is clean.
Generated files (INDEX.md) and files outside specs/ are not counted.
"""
from __future__ import annotations

import re
import subprocess
import sys

SPEC_FOLDER = re.compile(r"^specs/([^/]+)/")
SPEC_NUM = re.compile(r"^(SPEC-\d{4})")


def git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout


def changed_files(base: str, head: str) -> list[str]:
    return [p for p in git("diff", "--name-only", f"{base}...{head}").splitlines() if p]


def folders_at(ref: str) -> list[str]:
    try:
        return [f for f in git("ls-tree", "--name-only", f"{ref}:specs").splitlines() if f]
    except subprocess.CalledProcessError:
        return []


def front_matter_id(ref: str, folder: str) -> str | None:
    try:
        text = git("show", f"{ref}:specs/{folder}/spec.md")
    except subprocess.CalledProcessError:
        return None
    match = re.search(r"^---\r?\n(.*?)\r?\n---", text, re.S)
    if not match:
        return None
    for line in match.group(1).splitlines():
        if line.startswith("id:"):
            return line[3:].strip().strip("'\"")
    return None


def problems(base: str, head: str) -> list[str]:
    out: list[str] = []
    touched = {m.group(1) for p in changed_files(base, head) for m in [SPEC_FOLDER.match(p)] if m}
    if len(touched) > 1:
        out.append("A pull request changes one spec at a time; this one touches: " + ", ".join(sorted(touched)))

    base_folders = folders_at(base)
    head_folders = folders_at(head)
    numbers_on_base = {}
    for f in base_folders:
        m = SPEC_NUM.match(f)
        if m:
            numbers_on_base.setdefault(m.group(1), f)

    added = [f for f in head_folders if f not in base_folders]
    seen: dict[str, str] = {}
    for f in head_folders:
        m = SPEC_NUM.match(f)
        if not m:
            continue
        if m.group(1) in seen and seen[m.group(1)] != f:
            out.append(f"Two folders share the number {m.group(1)}: {seen[m.group(1)]} and {f}")
        seen.setdefault(m.group(1), f)

    for f in added:
        m = SPEC_NUM.match(f)
        if not m:
            out.append(f"New spec folder {f} has no SPEC-NNNN number (submit it from Spec Studio, or rename it)")
            continue
        if m.group(1) in numbers_on_base and numbers_on_base[m.group(1)] != f:
            out.append(f"{f} reuses {m.group(1)}, already taken by {numbers_on_base[m.group(1)]} on {base}")
        fm_id = front_matter_id(head, f)
        if fm_id is None:
            out.append(f"{f}/spec.md has no front matter id")
        elif fm_id.startswith("DRAFT-"):
            out.append(f"{f}/spec.md still carries a draft id ({fm_id})")
        elif fm_id != m.group(1):
            out.append(f"{f}/spec.md says id: {fm_id} but the folder is {m.group(1)}")
    return out


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    base = argv[1]
    head = argv[2] if len(argv) > 2 else "HEAD"
    found = problems(base, head)
    for p in found:
        print(f"::error::{p}")
    if not found:
        print("Spec pull request checks passed.")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
