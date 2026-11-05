# Spec format

How `specs/SPEC-NNNN-slug/spec.md` is structured. The front matter and
section list are the team's existing format. Every list is a numbered list,
so every bullet has an address (`3.2.1`) that people, Claude, and other specs
can reference.

`scripts/validate_and_index.py` checks front matter. `scripts/spec_structure.py`
checks the body. Agent rules are in [`CLAUDE.md`](CLAUDE.md).

---

## 1. Files

| Thing | Rule | Example |
|---|---|---|
| Spec folder | `specs/SPEC-NNNN-slug/`, flat, zero-padded ID | `specs/SPEC-0012-bulk-invoice-export/` |
| Spec file | `spec.md`, required | |
| Other docs | Next to `spec.md` (technical notes, contracts, interview notes, `*.html`, design drafts) | `api-contract.md` |
| Assets | `assets/` for images and other supporting files (`.gitkeep` when empty) | `assets/export-dialog.svg` |
| Links | Relative to `spec.md` | `[API contract](api-contract.md)` |

Link to another spec's `spec.md` or use `[[SPEC-NNNN]]`. Don't link into
another spec's folder.

## 2. Front matter

Owned by `validate_and_index.py`.

```yaml
---
id: SPEC-NNNN                 # must match folder prefix
title: <title>                # must match the H1
status: draft                 # draft | in-review | approved | archived (only humans set approved)
owner: <name>
modules: [Accounting]         # from modules.yml, non-empty
created: YYYY-MM-DD
updated: YYYY-MM-DD           # maintained by the validator; never edit by hand
superseded_by: null           # SPEC-NNNN or null
supersedes: null              # SPEC-NNNN or null
links:
  jira: []                    # URLs
  repos: []                   # URLs
---
```

## 3. Body

```
# <title>
## Table of Contents                 optional
## 1. Problem Statement
## 2. Background & Context
### 2.1 References
### 2.2 Key Constraints
### 2.3 Key Concepts
### 2.4 Out of Scope
## 3. Requirements
### 3.1 <free-form title>            as many as needed: 3.1, 3.2, 3.3 ...
## 4. Open Questions
## 5. Non-Functional Requirements
```

Rules:

1. Exactly one H1, equal to `title`.
2. Sections 1 to 5 are required, in this order, with this exact text
   (number, full stop, title). `Table of Contents`, if present, comes first.
3. Sub-sections 2.1 to 2.4 are required, in order, with this exact text.
4. Sub-sections of section 3 have free-form titles and are numbered `3.1`,
   `3.2`, and so on, with no gaps. Sections 1, 4, and 5 may also have numbered
   sub-sections (`4.1`) if needed.
5. H4 and deeper are allowed inside a sub-section. They're shown as content,
   not as separate levels in presentation mode.
6. Extra numbered sections after 5 (`## 6. Rollout`) are allowed. Any other
   H2 is an error.

## 4. Lists and bullets

Every list is a numbered list. Unordered bullets (`-`, `*`, `+`) are not used,
except in the Table of Contents.

Each section or sub-section is laid out as:

```markdown
### 3.2 Export Formats

As a finance admin, I want to choose the file format so that I can import
invoices into our ERP or hand PDFs to auditors.

1. The admin chooses one of three formats: CSV, PDF (ZIP), or CSV and PDF together.
2. The CSV has one row per invoice line.
   1. Amounts use a dot decimal separator.
   2. Files are UTF-8 with a byte order mark.
3. PDFs in the ZIP are named `<invoice-number>_<customer-name>.pdf`.
```

Rules:

1. **Description first (optional).** One or more paragraphs before the list:
   a user story, context, an image, or a table.
2. **Then one numbered list.** Nothing comes after the list in the same
   section or sub-section. Put tables and images in the description, or
   indented inside an item.
3. **Write the real numbers.** Items are numbered `1.`, `2.`, `3.` in the
   file, in order with no gaps, not `1.` repeated. Nested items are
   indented three spaces and also start from `1.`.
4. **Items or sub-sections, not both.** A section either has its own list
   or has sub-sections, so `4.1` always means one thing. Sections 2 and 3
   always have sub-sections, so their items live in 2.1 to 2.4 and 3.1
   onwards.
5. **Item metadata (optional).** One italic parenthetical at the end of the
   item's first line: `_(owner: Priya, due: 2026-11-07, status: resolved)_`.
6. **Open questions are resolved, not deleted.** Add `status: resolved` and a
   nested item starting `Answer:`.

## 5. Addresses and references

An item's address is its parent's number plus its position.

| What | Address | Example |
|---|---|---|
| Section | its number | `3` |
| Sub-section | its number | `3.2` |
| Item | parent number + position | `3.2.1`, `2.4.1`, `4.2` |
| Nested item | item address + position | `3.2.2.1` |
| Description | the sub-section or section | `3.2` |

References use double brackets:

| What | Syntax | Example |
|---|---|---|
| An item, section, or sub-section | `[[address]]` | `Uses the formats in [[3.2.1]]. See [[2.4]].` |
| Another spec | `[[SPEC-NNNN]]` | `Replaces the export in [[SPEC-0007]].` |
| Something in another spec | `[[SPEC-NNNN:address]]` | `Same limits as [[SPEC-0007:5.2]].` |
| A file in the folder | relative link | `[API contract](api-contract.md#csv-columns)` |

Every `[[...]]` must resolve. On GitHub the brackets render as plain text
(`[[3.2.1]]`), which stays readable.

**Renumbering.** Addresses come from position, so inserting, deleting, or
moving an item or sub-section renumbers the ones after it. Spec Studio does
the renumbering itself when a change is accepted: it rewrites the list
numbers, the Table of Contents, and every `[[...]]` in the spec that pointed
at a moved address. Anyone editing by hand has to do the same. References
from other specs (`[[SPEC-0999:3.2.1]]`) are not updated automatically, so
the checker reports them if they stop resolving, and the app warns when an
accepted change renumbers an address that another spec references.

## 6. Presentation mode

- Level 1 is sections, level 2 is sub-sections, level 3 is items.
- The front matter is a title card. `Table of Contents` is skipped, since the
  app shows its own.
- A sub-section's description is shown on the sub-section's own card, above
  a preview of its items. A section with its own list (like 4 and 5) shows
  its description the same way.
- A section with no sub-sections goes from level 1 straight to level 3.
- Nested items and H4 content are shown with their parent item.

## 7. Table of Contents

Optional. If present, it lists every section and sub-section with GitHub
heading anchors, in order, as in SPEC-0001 and SPEC-0007. The checker warns
when it's out of date, and Spec Studio regenerates it when headings change.

## 8. Structure check

| Code | Level | Rule |
|---|---|---|
| `FM2` | error | `id` doesn't match the folder prefix, or `title` doesn't match the H1 |
| `S1` | error | Section 1 to 5, or sub-section 2.1 to 2.4, is missing |
| `S2` | error | Section or sub-section out of order, wrong heading text, or unknown H2 |
| `S3` | error | No H1, or more than one |
| `S4` | error | Sub-section number doesn't match its section, or has a gap |
| `L1` | error | Unordered bullet outside the Table of Contents |
| `L2` | error | List numbers don't run 1, 2, 3 with no gaps |
| `L3` | error | Content after the list, or a second list, in the same section or sub-section |
| `L4` | error | Section has both its own list and sub-sections |
| `R1` | error | `[[...]]` doesn't resolve |
| `R2` | error | Relative link to a file that doesn't exist |
| `T1` | warn | Table of Contents doesn't match the headings |
| `A1` | warn | File in the spec folder isn't linked from `spec.md` (`.gitkeep` excluded) |
| `W1` | warn | Required section or sub-section is empty |
| `W2` | warn | Open question past its `due` date and not resolved |

The app shows these inline. Every change Claude proposes is re-checked, and a
proposal that adds an error is rejected before the user sees it.

## 9. Blank spec

````markdown
---
id: SPEC-NNNN
title: <title>
status: draft
owner: <name>
modules: [<module>]
created: YYYY-MM-DD
updated: YYYY-MM-DD
superseded_by: null
supersedes: null
links:
  jira: []
  repos: []
---

# <title>

## 1. Problem Statement

Who has the problem, what it costs them, and what success looks like.

## 2. Background & Context

Why now, and what a reader needs to know first.

### 2.1 References

1. [Technical notes](technical-notes.md)

### 2.2 Key Constraints

1. A constraint the solution must respect.

### 2.3 Key Concepts

1. **Term:** definition.

### 2.4 Out of Scope

1. Something a reader might expect that this spec leaves out.

## 3. Requirements

### 3.1 <Area>

As a <persona>, I want to <action> so that <outcome>.

1. The system must ...

## 4. Open Questions

1. Question? _(owner: <name>, due: YYYY-MM-DD)_

## 5. Non-Functional Requirements

1. Performance, security, accessibility, or limits.
````
