<!-- Adapted from deepseek-ai/deepseek-harness (MIT): docs/postmortem/README.md -->
# Post-mortems

English | [中文](README.zh.md)

Incident write-ups: a bug reached a place it should not have (a real user, a merged PR, a release), and the interesting part is *why our process let it through*, not just the one-line fix.

A post-mortem is not an [Agent Note](../../.agents/notes/README.md). An Agent Note records a deliberate design decision or proposed future work. A post-mortem is a backward-looking record of a failure: what broke, the mechanism, why every safety net missed it, and the concrete guardrails added so the same class of bug fails loudly next time.

Write one when a bug is **subtle** (the mechanism is non-obvious), **systemic** (the reason it escaped is a gap in tests, tooling, or conventions, not a one-off typo), and **costly to rediscover**. Link the guardrails (tests, AGENTS.md rules, Agent Notes) the post-mortem motivated.

Every post-mortem opens with an **Executive summary**: one short paragraph a busy reader can absorb in thirty seconds. It states what broke, the root cause in plain terms, why it escaped, and the durable lesson. Detailed sections (Summary, Timeline, Root cause, Guardrails) follow.

| # | Title |
|---|---|
| — | No post-mortems yet. |
