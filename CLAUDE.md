# Team specs repo

This file tells Claude Code how to work in this repo. The desktop app
(Spec Studio) reads it too — it is the source of repo-wide rules.

## Rules

- One spec per folder under `specs/`, named `SPEC-NNNN-slug/`.
- Edit `spec.md`. Reference files sit beside it; assets go in `assets/`.
- Never set `status: approved`. Never edit `updated` or `INDEX.md` — the
  validator owns them.
- Never hand-edit `spec-graph.json` or `open-questions.md`. The validator
  rebuilds the graph; the app owns the questions file.
- Use `[[address]]` for in-spec refs ("[[3.2.1]]") and
  `[[SPEC-NNNN:address]]` for cross-spec refs.
- Keep H1 as the spec title and front matter required keys (id, title,
  status, modules). Anything else about the template is a recommendation,
  not a contract (SPEC-FORMAT §8).

## Scripts

- `scripts/validate_and_index.py` — pre-commit validator. Rebuilds
  `INDEX.md`, `updated`, and every spec's `spec-graph.json`.
- `scripts/spec_structure.py` — the structure check library.
- `scripts/spec_graph.py` — the graph builder (GRF-14). Deterministic
  output; conflicts are regenerated, never hand-merged.

## Spec graph

Each spec folder holds a `spec-graph.json` committed alongside `spec.md`.
Agents outside the app should read it before editing to find related
blocks, and run `validate_and_index.py` after editing to refresh it.
Inferred relations have a confidence; stale ones are re-checked before use.
