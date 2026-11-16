# Tianshu gates

Documentation and Agent Note gates, adapted from deepseek-harness (MIT). Copied into a project as `scripts/tianshu/`.

## Install

    npm --prefix scripts/tianshu ci

## Commands

    npm --prefix scripts/tianshu run gates -- --repo "$PWD"
    npm --prefix scripts/tianshu run gate -- <name> --repo "$PWD" [--staged]
    npm --prefix scripts/tianshu test

`--staged` checks the Git index (what the commit will contain); use it from pre-commit. Exit 0 = pass, 1 = violations (printed as `file:line rule message`), 2 = usage or config error.

## Gates

| Name | Checks | Config |
|---|---|---|
| agent-note-format | Agent Note tree layout, header block, required sections, alternatives | `agentNotes.legacyCutoff` (grandfather date) |
| archived-agent-notes | Frozen archive: triplets, archive dates, sealed hashes | `.tianshu/archived-notes.manifest.json` (`--write` seals new files) |
| doc-budgets | Word ceilings for budgeted docs | `.tianshu/doc-budgets.json` |
| md-links | Relative links, images, and `#anchors` resolve | none |
| md-wrap | Each prose paragraph is one physical line | none |
| translation-pairing | `.zh.md` pairs for every README, root `CONTRIBUTING.md`/`SAFETY.md`/`BRAND_GUIDELINES.md`, and everything under `.agents/notes/` and `docs/` except `AGENTS.md` files; structure match, section hashes, language switchers | `translation.*` (opt-in; `include` adds paths, `roots` re-bases scope and recorded link targets under vendored trees) |
| repository-references | No commit hashes (checked against the Git object DB) or forbidden org URLs | `repositoryReferences.*` |
| issue-policy | PR body has a same-repo Issue reference; labels from `kit/labels.json`: exactly one type/* (type/bug also exactly one severity/* and one env/*), at most one priority/*, at least one area/*; retired names (kind/*, p0-p3, type::* and the other company scoped labels) and unknown names in a closed family fail. In GitLab or GitHub CI, every referenced Issue must exist and carry the same labels except area/*; outside CI that part is skipped with a notice | env `TIANSHU_PR_BODY`, `TIANSHU_PR_LABELS`; Issue API via `CI_JOB_TOKEN` or `GITHUB_TOKEN`, overridden by `TIANSHU_API_TOKEN` (not in `gates`) |

`gates` runs everything except issue-policy. `gate translation-pairing --write --all` records pair hashes.

## Config files

`.tianshu/config.json` (all keys optional; missing file means defaults with a notice):

    {
      "scope": { "exclude": [] },
      "repositoryReferences": { "forbiddenOrganizations": [], "allowedUrlPrefixes": [] },
      "translation": {
        "enabled": true, "sourceLanguage": "en", "counterpartLanguage": "zh",
        "exclude": [], "include": [], "roots": [], "repositoryBlobRoot": null
      },
      "agentNotes": { "legacyCutoff": null }
    }

Default excludes: `node_modules`, `.git`, and `scripts/tianshu`. Archived notes are skipped by the md and translation gates.

## Known gaps

- Glob matching is a small dot-inclusive matcher (`lib/context.ts`), not Node's `fs.glob`.
- Commit-hash check needs a Git repository; otherwise it prints a notice and is skipped.
- Translation quality is not checked, only structure, hashes, and links.
