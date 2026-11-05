---
id: SPEC-0994
title: Monthly close checklist
status: draft
owner: Dana
modules: [Accounting]
created: 2026-10-20
updated: 2026-10-20
superseded_by: null
supersedes: null
links:
  jira: []
  repos: []
---

# Monthly close checklist

## 1. Problem Statement

Finance teams rely on a monthly close checklist. The spec names each
step they need, and defers to [[SPEC-0999:3.2.1]] for the invoice
export step. That ref is a **cross-spec reference** and should produce
a template warning on move (SPEC-FORMAT §5), never an error.

## 2. Background & Context

### 2.1 References

- The close process this team uses today.
- Finance's quarterly reconciliation guide.

### 2.2 Key Constraints

- The checklist runs on the first business day of the month.
- Each step is a numbered item.

### 2.3 Out of Scope

- Reconciliation itself (handled by Finance).
- Auditor packaging (handled quarterly).

## 3. Requirements

### 3.1 Checklist steps

1. Export every open invoice using `[[SPEC-0999:3.2.1]]` (CSV format).
2. Reconcile open invoices against the ledger.
3. Email the finance lead when complete.

### 3.2 Validation

Each step produces a check-off entry in the audit log.

## 4. Open Questions

None.

## 5. Non-Functional Requirements

- The checklist completes within one business day.
