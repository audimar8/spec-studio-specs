---
id: SPEC-0993
title: Exchange rate import
status: draft
owner: Dana
modules: [Accounting]
created: 2026-11-05
updated: 2026-11-05
superseded_by: null
supersedes: null
links:
  jira: []
  repos: []
---

# Exchange rate import

## 1. Problem Statement

Admins paste exchange rates by hand every morning. This spec imports them
from the treasury feed instead. Its reference files are still being
written, so some of them don't parse yet (GRF-16).

## 2. Background & Context

### 2.1 References

1. [Import settings](import-settings.json): half-written, not valid JSON yet.
2. [Rate sample](rate-sample.csv): pasted from a spreadsheet, rows have uneven columns.
3. [Rollout notes](rollout-notes.md): free text, no headings yet. The rollout plan is in [Rollout notes](rollout-notes.md#rollout-plan).
4. [Treasury feed](treasury-feed.xml): the feed's XML shape, see its [rate element](treasury-feed.xml#rate).
5. [Import flow](import-flow.mmd): the import steps as a Mermaid flowchart, starting at [Fetch](import-flow.mmd#Fetch). Test, Test.

## 3. Requirements

### 3.1 Import

1. Rates import every morning at 06:00 UTC from the treasury feed.
2. A rate that differs from yesterday's by more than 5% is held for review. See [[3.1.1]]. [Rate sample](rate-sample.csv)
