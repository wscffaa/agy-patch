<!-- Adapted from deepseek-ai/deepseek-harness (MIT): docs/defensive-patterns/README.md -->
# Defensive patterns

English | [中文](README.zh.md)

Hard-won rules. Each pattern in this directory is a requirement enforced in review, stated as the rule and the defect it prevents. Every rule states what must hold, the condition a reviewer judges it by, its boundary and who approves an exception, and a correct and a wrong example. Read the page for the artifact you are about to change, before you change it.

## Why these rules

Five habits cover most of what follows, and each page applies them to one artifact:

- **Make correctness explicit.** Write it into the structure (named call points, explicit lifecycles, explicit conditions and types) rather than compensating for it afterwards with timing.
- **Keep one source of truth.** One read path for a piece of data, one home for a fact, one owner for shared state.
- **Extend through the registered seam.** A new capability registers. An existing carrier stops taking new logic instead of growing a branch inside it.
- **Keep the change face equal to the review face.** A change carries only the lines its stated behavior change needs. A migration moves code rather than rewriting it. A performance-sensitive change carries its measurement.
- **Require evidence.** A claim is falsifiable and recomputable: measured before and after, or checked by a gate.

| Changing | Read |
|---|---|
| Public interfaces, package shape, build outputs, dependency declarations | <!-- add page: package-surface.md --> |
| Remote services, request dispatch, business ownership at the API layer | <!-- add page: remote-and-api.md --> |
| UI components, state stores, effects | <!-- add page: client-components.md --> |
| Persisted records, retention, read paths | <!-- add page: persistence.md --> |
| Timing, shared state, disposal, callbacks, subprocesses, migrations | <!-- add page: general.md --> |

Type definitions and per-subsystem semantics live in [subsystems/](../subsystems/README.md) once the project has them. This directory carries the rules; the semantics pages carry what the types mean.
