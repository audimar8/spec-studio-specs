---
id: SPEC-0998
title: Unnumbered headings
status: draft
owner: Austin
modules: [Platform]
created: 2026-10-20
updated: 2026-10-20
superseded_by: null
supersedes: null
links:
  jira: []
  repos: []
---

# Unnumbered headings

## Problem Statement

Some PMs write their specs without numbering the headings or the list
items. The app must still address every block positionally so `[[refs]]`
can point at them (14.25).

## Background & Context

### References

- Team conventions page.
- The Spec Studio design brief.

### Key Constraints

- Positional addresses are computed from the hierarchy, not the written
  numbers. A second H2 is `2`, its third H3 is `2.3`, and the first list
  item under that is `2.3.1`.
- The written number is kept when present, and only rewritten when the
  spec already numbers that kind of block.

### Out of Scope

- Rewriting an unnumbered spec to be numbered. That is a user action.

## Requirements

### Positional addressing

- Every block has an address derived from its position.
- The address shows in the gutter so a PM knows what `[[refs]]` to write.

### Reference writing

- `[[2.3.1]]` resolves to this block in the Spec Studio parser.
- Writing `[[refs]]` to an unnumbered spec works the same as a numbered
  one, from the app's point of view.

## Open Questions

None yet.

## Non-Functional Requirements

- Rendering an unnumbered spec is as fast as rendering a numbered one.
