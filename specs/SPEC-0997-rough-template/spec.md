---
id: SPEC-0997
title: Rough template
status: draft
owner: Austin
modules: [Billing]
created: 2026-10-20
updated: 2026-10-20
superseded_by: null
supersedes: null
links:
  jira: []
  repos: []
---

# Rough template

## Table of Contents

- [1. Problem Statement](#1-problem-statement)
- [2. Background & Context](#2-background--context)
- [3. Requirements](#3-requirements)

## 1. Problem Statement

This spec departs from the template on purpose, so the app's structure
check and the parser can be exercised on realistic rough content.

See [[9.9.9]] for the primary scenario — this ref is intentionally
broken (R1).

## 2. Background & Context

### 2.1 Visuals

The embedded image below used to be inline. The app renders embedded
images as linked references (IMG-1, IMG-2), opening in the right pane.

![Export dialog mock](./assets/missing-mock.png)

The file link above is intentionally broken (R2) — `missing-mock.png`
does not exist in `assets/`.

### 2.2 Hierarchy

#### 2.2.1 Deep heading

An H4 lives here. The template says headings stop at H3 (SPEC-FORMAT §3),
so this should produce a template-difference warning (T1), not an error
(14.21).

- An item under an H4 is still addressable.
- The parser falls back to numbering list items positionally.

## 3. Requirements

### 3.1 Behaviour

- Template differences are shown as information, not errors.
- Broken refs stay errors.
- Broken file links stay errors.

## 4. Open Questions

None.

## 5. Non-Functional Requirements

- The structure check runs on this spec without crashing.
