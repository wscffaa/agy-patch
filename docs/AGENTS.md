<!-- Adapted from deepseek-ai/deepseek-harness (MIT): docs/AGENTS.md -->
# AGENTS.md — The documentation standard

This file defines document structure, Markdown tiers, writing rules, and word budgets. Budgets live in [.tianshu/doc-budgets.json](../.tianshu/doc-budgets.json). Use the [Agent Notes README](../.agents/notes/README.md) for decision records.

## Document structure

Human-facing documentation lives under `docs/`. Agent Notes are outside this scope. A document's subject and tree position fix its scope: describe its own subject at appropriate detail, and link to the owning descendant for lower-level detail.

Classify every document as a tutorial or a reference. Tutorials follow an ordered path to an outcome and introduce only what each step needs. References define a lookup scope and current behavior without a teaching sequence. Label a section when its tutorial or reference content is small.

Author in this order: locate the document in the tree; set its permitted detail; choose tutorial or reference; for a tutorial, order concepts by prerequisite and difficulty; relocate descendant-owned detail; replace lower-level explanations with links to their owners.

## The tier taxonomy: one home per fact

Each fact has one home: the tier whose job it is. Elsewhere, link there.

| Tier | Job | Does NOT belong there |
|---|---|---|
| Root `AGENTS.md` | Standing orders an agent needs in every session, one to three lines each, linking the home | Stories, worked examples, situational procedures, anything restated from a linked home |
| Subtree `AGENTS.md` | Orders specific to that subtree | Repository-wide rules the root file already carries |
| [architecture.md](architecture.md) | Ordered map of composition, core modules, data flow, and extension points; read before changing source | Type definitions (→ subsystems), per-module detail (→ module READMEs), decision rationale (→ Agent Notes) |
| [subsystems/](subsystems/README.md) | One reference page per subsystem: type definitions and semantics | Behavior narration (→ architecture.md) |
| [Agent Notes](../.agents/notes/README.md) | Decision records: the why, what was given up, and required verification | Migration plans and spec-speak once the decision has shipped |
| [defensive-patterns/](defensive-patterns/README.md) | Rules enforced in review, split by artifact | Type definitions and semantics (→ subsystems), decision rationale (→ Agent Notes) |
| [postmortem/](postmortem/README.md) | Incident stories: the only tier where war-story narrative belongs | Standing rules (→ root or defensive-patterns) |
| [cookbook/](cookbook/README.md) | Step-by-step how-tos with numbered verify steps | Design rationale (→ the Agent Note each guide links) |
| Module README | The per-module contract: configuration, semantics, limitations, extension points | Restated JSDoc, generated catalogs, other modules' concerns |
| `user/` | Product-facing guides published by the documentation website | Generated reference tables, contributor procedures, decision history |
| Generated reference | Exhaustive sources regenerated from code and freshness-gated | Hand edits to generated output |

Placement: bugs → postmortems; rationale → Agent Notes; procedures → cookbooks; type definitions → subsystems; module contracts → READMEs; standing orders → root `AGENTS.md` with a rationale link; review-enforced rules → `defensive-patterns/`.

## Writing rules

- **Document current state.** Keep history in commits, PRs, Agent Notes, or postmortems. Prose names live mechanisms, not changes.
- **One current file per document.** Never keep side-by-side version copies such as `-v7`, `-v8`, `_final`, or `_old`; history lives in git. Working material lives in the project's ignored `tmp/<issue>-<slug>/` until `tianshu-harvest` moves what lasts to its tier; handoff material goes to an Issue or MR comment.
- **One physical line per paragraph.** Use editor soft-wrap. Code blocks, tables, and list structure keep their formatting.
- **Bilingual pairs update together.** Each English document has a `.zh.md` counterpart with the same section structure. Update both in the same change. Instruction files (`AGENTS.md`, `SKILL.md`) are English-only and have no counterpart; the `translation-pairing` gate skips them.
- **Comments and JSDoc state complete contracts, not reasoning transcripts.** Preserve behavior, failure, timing, ownership, and exceptions. Delete narration, test walkthroughs, review analysis, and code restatement.
- Write directly: name actors and facts. Name the exact check, type, API, or behavior instead of vague terms such as "gate", "surface", or "seam".
- Use relative Markdown links for current files. Historical references use tags, issue numbers, or PR numbers.

## Word budgets

[.tianshu/doc-budgets.json](../.tianshu/doc-budgets.json) sets ceilings for standing documents. The budget gate rejects excess or missing files.

When the gate fails:

1. **Relocate** content that belongs in another tier; leave a one-line link.
2. **Condense** content that belongs here but can be shorter.
3. **Raise** the ceiling only when the words need the space; justify the manifest diff in the PR. A too-low ceiling is a budget bug.

Ceilings are guardrails, not reduction targets. Keep at least 5% headroom below a ceiling. Lower a ceiling only when the document still has room.

## The slop checklist

Hunt these in any document:

- Duplicated rules: search a distinctive phrase; keep one home and link the rest.
- History outside its permitted tier: state current facts and link the historical owner.
- Implementation-status annotations ("implemented!", "future: …") in prose or diagrams. Status rots; manifests and source carry it.
- Hand-restated catalogs, JSDoc, or inventories of tests and modules when source or a generator is authoritative.
- Reasoning transcripts: step-by-step narration, proof of obvious branches, test walkthroughs, or rejected local alternatives. Keep the resulting contract; delete the path used to derive it.
- Rationale repeated beside sibling methods instead of once at the owning helper.
- Paragraph walls: one paragraph carrying several rules and parenthetical asides. Split it or move the detail to its home.
- Emphasis inflation: bold, CAPS, or "critically" everywhere means nothing stands out.
- Spec-speak in `implemented` Agent Notes: "should", migration plans, acceptance checklists.

## Repository references

Use relative Markdown links for current files. Use tags or PR numbers for historical references.
