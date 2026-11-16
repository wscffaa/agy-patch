<!-- Adapted from deepseek-ai/deepseek-harness (MIT): .agents/notes/archived/AGENTS.md -->
# AGENTS.md — Archived Agent Notes

Archived Agent Note triplets under the class directories are frozen historical snapshots, not current authority. Never edit, reformat, translate, repair, delete, or move a sealed artifact. Use an active Agent Note or current documentation for new decisions and facts.

The archival change may only relocate a complete English/Chinese/sidecar triplet, insert the identical `Archived: YYYY-MM-DD` line below both `Status: implemented` lines, re-record the sidecar, and repair or delete inbound links. Do not inspect, verify, or repair links out of archived notes.

Run the `tianshu-archive-agent-notes` skill workflow. Record new artifact hashes in `.tianshu/archived-notes.manifest.json` with the Tianshu `archived-agent-notes` gate in write mode. The normal gate rejects changed or missing sealed artifacts, incomplete triplets, unknown class folders, and invalid archive metadata.
