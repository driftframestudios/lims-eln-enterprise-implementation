---
name: contextual-jargon-scan
description: Classifies specialist and collaboration-local wording in a bounded Enterprise Implementation corpus and revises replaceable shorthand into ordinary language. Applies in stride when public orientation, runbooks, evidence prose, or cross-repository instructions may assume context the reader does not share.
source_band: public_possible
skill_version: 0.1.0
upstream_repository: driftframestudios/human-ai-systems-exemplars
upstream_path: .agents/skills/contextual-jargon-scan/SKILL.md
upstream_revision: 0c023343e46cd9b1333a63c2d509787352fbad14
upstream_blob_sha1: 3c3a94db99152385253e0281c8afa8fea8208ac5
upstream_sha256: da383f99eaff364d7e17c3bff93d8da618ec95894a45ff78a9620d8d7fc81523
adaptation_relation: repository_local_derivative
---

# Enterprise Implementation contextual jargon scan

## Contract

- **What:** A context-aware review that distinguishes exact implementation and
  evidence language from shorthand a reader must decode.
- **When:** A bounded public, cross-repository, release, evidence, runbook, or
  instruction surface is already receiving material prose changes.
- **Boundaries:** Schema keys, identifiers, versions, code, quotations,
  accessibility meaning, established technical and regulated terms, and
  source-owned language retain their fidelity. Search tools produce candidates;
  contextual reading determines whether a revision helps.
- **Result:** A scoped occurrence map, targeted revisions, intentional
  retentions that affect future work, and a verification signal tied to the
  changed prose.

## Rules

### Rule: Scope and reader come first

Name the files already changing, intended readers, exclusions, and candidate
word families. Keep an in-stride scan within the active implementation surface.

### Rule: Search results are candidates

Search inflections and nearby forms with enough context to read their role.
Counts locate repeated language; they do not establish a defect or completion
threshold.

### Rule: Classify each material occurrence

Treat an occurrence as ordinary language, exact technical or governed
vocabulary, quoted or source-owned language, useful compact language, or
replaceable shorthand. The same word can receive several classifications.

### Rule: Replacement follows function

For replaceable shorthand, name the concrete implementation object, evidence
action, authority relation, source boundary, or consequence it was carrying.
Use the smallest ordinary-language revision that preserves technical depth.

### Rule: Exact implementation language can stay

Retain terms such as idempotency, compare-and-set, row-level security, Flyway,
SHA-256, source revision, evidence binding, and recovery when they are
technically exact. Define a term near first use when the intended reader
otherwise lacks the relationship it names.

### Rule: Fidelity-bearing text keeps its owner

Preserve code, JSON keys, schema vocabulary, release identities, citations,
and accessibility meaning. Route a disputed source-owned term to its authority
rather than normalizing it locally.

### Rule: Verification returns to the reader

Read every changed sentence in its heading, paragraph, table, metadata, or
accessibility context. Run the owning structural, behavioral, and deterministic
checks after the prose review.

## Operating sequence

1. Bind the corpus, readers, exclusions, and candidate word families.
2. Gather occurrences with surrounding text.
3. Classify each decision-changing occurrence.
4. Retain, define, revise, or defer using the smallest useful action.
5. Re-read nearby headings, links, metadata, and accessibility text.
6. Run the receiving surface's existing checks.
7. Return the scope, changes, meaningful retentions, evidence, and any receiver.

## Completion

The scan completes when a reader can retrieve the implementation objects,
actions, authority relations, and consequences without relying on
collaboration-local context; retained specialist language has an exact or
useful role; and the receiving surface's behavior remains verified.
