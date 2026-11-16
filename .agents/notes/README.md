<!-- Adapted from deepseek-ai/deepseek-harness (MIT): .agents/notes/README.md -->
# Agent Notes

English | [中文](README.zh.md)

One kind of design doc lives here. An **Agent Note** records a decision or proposal that affects this codebase: the *why* and *what we gave up*, the parts code and docs cannot carry. This file defines where Agent Notes live, when to write one, and [the in-file format](#the-file-format).

## Layout and naming

Every Agent Note has two axes, both encoded in its **path**: `{lifecycle}/{class}/yyyy-mm-dd-topic-title.md`.

- **Lifecycle** (the top-level folder) is the Agent Note's status. An Agent Note moves between folders as that status changes:
  - **`proposed/`**: proposals reviewed before implementation; not yet built (or only partly).
  - **`implemented/`**: the decision shipped. The file records what was decided and what was rejected, and is **kept current with what actually shipped**: when the code later moves a file, renames a package, or changes a key or default, the Agent Note is updated in the same change to match. Facts only (paths, names, structure), not the decision itself. See [implemented/AGENTS.md](implemented/AGENTS.md).
  - **`rejected/`**: the proposal was considered and declined. Keep it only while its rationale prevents a tempting, meaningful mistake; otherwise delete the complete triplet.
- **Class** (the nested folder) is the *kind* of decision. See [Classification](#classification).

The date in the filename is when the topic was **first proposed** (per git history). Cross-references between Agent Notes use relative Markdown links (`[topic](../../implemented/architecture/2026-…-….md)`), never bare prose, so the gate can check them and they survive moves between folders.

The active lifecycle tree is the working inventory: browse its folders or search the repository. Do not add a centralized `INDEX.md`: it duplicates path metadata and makes unrelated note changes contend on one generated file. Implemented records with historical value but little future guidance move to the frozen [`archived/`](archived/AGENTS.md) tree.

## Classification

Each Agent Note belongs to one path-encoded class from the closed set enforced by the `agent-note-format` gate. The gate rejects other folders. Adding a class requires updating the canonical set and this section.

| Class | What it covers |
|---|---|
| `feature` | A new user- or model-facing capability. |
| `bug-fix` | Corrects a defect or closes a gap a postmortem surfaced. |
| `simplification` | Removes code, behavior, or surface area without adding a capability. |
| `architecture` | A structural decision about the **shipped source**: how modules relate, what the runtime vocabulary is. |
| `process` | Tooling, policy, or workflow **around** the code: gates, package manager, vendoring. Not runtime behavior. |
| `testing` | Test infrastructure and strategy. |

The `architecture` / `process` line: **architecture** is about the source we ship; **process** is the surrounding tooling and workflow. (`refactor` is deliberately absent. It overlaps `simplification`, whose discriminator, "does observable behavior change?", already covers it.)

## Archiving and deletion

Delete an implemented Agent Note that only describes small UI adjustments or purely mechanical changes. Delete its English, Chinese, and sidecar files together, and repair or remove inbound links. A local bug fix, performance change, new capability, or substantive behavior decision does not qualify merely because its implementation is small. Archive other implemented notes only when the shipped decision is complete, its rationale is unlikely to guide future work, and the record still has historical value. Keep it active when its alternatives, ownership boundary, negative guarantee, durable or wire semantics, security rule, or reintroduction condition remains useful. Never archive a proposed note: reject an obsolete proposal. Keep a rejected note only while it prevents a plausible mistake. Use the `tianshu-archive-agent-notes` skill workflow rather than word count, age, or a target quota.

The archive is path-encoded as `archived/{class}/yyyy-mm-dd-topic-title.md`. `implemented` is deliberately absent because only implemented notes can enter it. An archival change moves the complete English/Chinese/sidecar triplet, retains `Status: implemented`, inserts the same `Archived: YYYY-MM-DD` line immediately below that status in both language files, re-records the sidecar, and repairs or deletes inbound links. Those are the only permitted content changes during archival. Run the `archived-agent-notes` gate afterwards: `npm --prefix scripts/tianshu run gate -- archived-agent-notes --repo "$PWD"`.

Once sealed, every archived triplet is permanently frozen. Do not edit, translate, reformat, update, move, or delete it, and do not treat it as authority for current behavior. Active prose may still link into an archived note when it intentionally cites history.

## When to write one

Add or update an Agent Note in the same PR only for lasting decision rationale that code, tests, and existing documentation do not explain. A proposal for substantial future work starts in `proposed/`; a decision already made starts in `implemented/`. Pick the class folder that matches the decision.

Updating the Agent Note that already owns the decision satisfies the rule; do not create a duplicate. Mechanical or local edits, including local UI presentation and interaction changes, are exempt. An Agent Note is never edited into a *different decision*: supersede it with a new one, and keep both notes cross-linked unless the old note is later fully consolidated under the rule below.

An implemented Agent Note that is fully superseded may be consolidated into the current owning note and deleted. Before deletion, the owner must preserve every unique rationale, alternative, consequence, required verification, and named coverage gap; repair every inbound link; and delete the Chinese counterpart in the same change. Partial supersession does not qualify: keep both notes cross-linked and update every fact that remains current. Consolidation must not rewrite the old file into its opposite, and must not rely on git history as the only copy of the rationale.

## The file format

Every active Agent Note follows one in-file format, enforced by the `agent-note-format` gate:

```sh
npm --prefix scripts/tianshu run gate -- agent-note-format --repo "$PWD"
```

Archived notes keep the format they had when sealed, plus the archive-date line above.

### The header block

The first three lines of every Agent Note are exactly:

```markdown
# Agent Note: <title>

Status: <status>
```

followed by a blank line. The `Status:` value is one of three forms, and must agree with the lifecycle folder the file sits in. The gate cross-checks them:

- `Status: proposed`
- `Status: implemented`
- `Status: rejected — <why, in one line>`

The status carries no dates and no parentheticals: the filename holds the first-proposed date, git holds everything else. The rejection reason is the one status with content, because a rejected note's verdict is the fact readers come for.

### The body skeleton

Every Agent Note opens its body with `## Problem`: the motivation, written to stand without the solution. What follows depends on the lifecycle. Recurring sections use these canonical names and nothing else. Genuinely bespoke technical sections (package topology, wire contracts, schemas) remain free-form between the required ones.

#### `proposed/`

```markdown
## Problem
## Proposal
…bespoke sections…
## Alternatives considered
## Acceptance criteria
## Risks
```

`## Proposal` is the intended change and may speak in the future tense. `## Acceptance criteria` says what observable state means done. `## Risks` covers what could go wrong and what the change knowingly gives up.

#### `implemented/`

```markdown
## Problem
## Decision
…bespoke sections…
## Alternatives considered
## Consequences
```

`## Decision` describes shipped reality in the present tense, and the whole file is kept current with it per [implemented/AGENTS.md](implemented/AGENTS.md). `## Consequences` records what the trade-off cost **and** bought. Proposal-era headings are spec-speak here and the gate rejects them: `## Proposal`, `## Plan`, `## Migration plan`, and `## Acceptance criteria` may not appear in an implemented Agent Note. A `## Testing`, `## Deferred`, or `## Related` section is fine where it states present-tense fact.

#### `rejected/`

A rejected Agent Note is the proposal, frozen. It keeps whatever proposal-time sections it had, and the verdict lives on the `Status:` line. Only the header block, the `## Problem` opener, a `## Proposal` section, and the Alternatives-considered mandate below apply.

### Alternatives considered: mandatory

Every Agent Note carries an `## Alternatives considered` section: each genuine alternative and why it lost, one bold-led paragraph per alternative or a `### Why not <X>?` subsection per contested one. A decision recorded without what it beat invites re-litigation, which is the failure Agent Notes exist to prevent.

Alternatives are recorded, never invented. An Agent Note whose alternatives cannot be reconstructed from the record carries this exact comment in place of the section. The gate accepts it only for pre-format files:

```markdown
<!-- agent-note-format: alternatives-not-recorded (pre-format Agent Note) -->
```

### Moving between lifecycles

Moving a file between lifecycle folders means updating the `Status:` line and re-satisfying that folder's skeleton in the same change. The gate fails the move otherwise. `proposed/` → `implemented/` rewrites `## Proposal` into a present-tense `## Decision`, folds `## Acceptance criteria` and `## Risks` into `## Consequences` (or a present-tense `## Testing` section), and replaces plans with what shipped. `proposed/` → `rejected/` only adds the reason to the `Status:` line and freezes the file.

### Chinese counterparts

A `.zh.md` counterpart mirrors its English sibling's structure section-for-section under the [documentation standard](../../docs/AGENTS.md). The machine-checked header tokens (`# Agent Note: ` and the `Status:` line) stay in English verbatim. The format gate skips `.zh.md` files; the translation-pairing gate checks their consistency:

```sh
npm --prefix scripts/tianshu run gate -- translation-pairing --repo "$PWD" --staged
```
