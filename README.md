# Team specs repo

This repo holds every product spec, one folder per spec. See
`SPEC-FORMAT.md` for the template and `scripts/validate_and_index.py`
for the validator.

Spec Studio is the desktop app for editing these specs. It never writes
`updated`, `status: approved` or `INDEX.md` — the validator owns those.

## Modules

See `modules.yml` for the current module list. Every spec's front
matter must name one or more modules.

## Workflow

1. `git switch -c <you>/SPEC-NNNN-short-name` from latest `main`.
2. Edit `spec.md` in Spec Studio. Reference files live beside it.
3. Commit — the validator runs first and may block.
4. Open a PR against `main`. Never merge your own PR.
