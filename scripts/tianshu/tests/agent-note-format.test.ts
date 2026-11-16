import assert from 'node:assert/strict'
import { describe, it } from 'node:test'
import { agentNoteFormat } from '../gates/agent-note-format.ts'
import { makeRepo } from './helpers.ts'

const PROPOSED = `# Agent Note: Sample decision

Status: proposed

## Problem

The gate set needs a sample note.

## Proposal

Add one sample note.

## Alternatives considered

**Skip it.** The format gate then has nothing to check.

## Acceptance criteria

The format gate passes.

## Risks

None.
`

const IMPLEMENTED = `# Agent Note: Shipped decision

Status: implemented

## Problem

Something was missing.

## Decision

The gate exists.

## Alternatives considered

**Ad hoc checks.** They drift.

## Consequences

Maintenance cost.
`

const NOTE = '.agents/notes/proposed/feature/2026-10-30-sample.md'

describe('agent-note-format', () => {
  it('passes a conforming proposed note', (t) => {
    const fx = makeRepo({ [NOTE]: PROPOSED })
    t.after(() => fx.cleanup())
    assert.deepEqual(agentNoteFormat.run(fx.ctx(), []), [])
  })

  it('passes a conforming implemented note under implemented/process', (t) => {
    const fx = makeRepo({ '.agents/notes/implemented/process/2026-10-30-shipped.md': IMPLEMENTED })
    t.after(() => fx.cleanup())
    assert.deepEqual(agentNoteFormat.run(fx.ctx(), []), [])
  })

  it('reports a missing Alternatives considered section', (t) => {
    const fx = makeRepo({ [NOTE]: PROPOSED.replace('## Alternatives considered', '## Options') })
    t.after(() => fx.cleanup())
    const out = agentNoteFormat.run(fx.ctx(), [])
    assert.ok(out.some(v => v.file === NOTE && v.message.includes('Alternatives considered')))
  })

  it('reports a proposal-era heading in an implemented note', (t) => {
    const body = IMPLEMENTED.replace('## Consequences', '## Acceptance criteria\n\nDone.\n\n## Consequences')
    const fx = makeRepo({ '.agents/notes/implemented/process/2026-10-30-shipped.md': body })
    t.after(() => fx.cleanup())
    const out = agentNoteFormat.run(fx.ctx(), [])
    assert.ok(out.some(v => v.message.includes('proposal-era heading')))
  })

  it('reports an unknown class folder and a centralized INDEX.md', (t) => {
    const fx = makeRepo({
      '.agents/notes/proposed/refactor/2026-10-30-sample.md': PROPOSED,
      '.agents/notes/INDEX.md': '# index\n',
    })
    t.after(() => fx.cleanup())
    const rules = agentNoteFormat.run(fx.ctx(), []).map(v => v.message)
    assert.ok(rules.some(message => message.includes('unknown class folder "refactor"')))
    assert.ok(rules.some(message => message.includes('centralized Agent Note indexes are forbidden')))
  })

  it('reports a filename without the yyyy-mm-dd prefix', (t) => {
    const fx = makeRepo({ '.agents/notes/proposed/feature/sample.md': PROPOSED })
    t.after(() => fx.cleanup())
    assert.ok(agentNoteFormat.run(fx.ctx(), []).some(v => v.message.includes('yyyy-mm-dd-topic.md')))
  })

  it('reports a wrong status line for the folder', (t) => {
    const fx = makeRepo({ [NOTE]: PROPOSED.replace('Status: proposed', 'Status: implemented') })
    t.after(() => fx.cleanup())
    assert.ok(agentNoteFormat.run(fx.ctx(), []).some(v => v.message.includes('status grammar')))
  })

  it('rejects the grandfather comment when no legacyCutoff is configured', (t) => {
    const body = PROPOSED.replace('## Alternatives considered\n\n**Skip it.** The format gate then has nothing to check.\n', '<!-- agent-note-format: alternatives-not-recorded (pre-format Agent Note) -->\n')
    const fx = makeRepo({ [NOTE]: body })
    t.after(() => fx.cleanup())
    assert.ok(agentNoteFormat.run(fx.ctx(), []).some(v => v.message.includes('legacyCutoff')))
  })

  it('accepts the grandfather comment for notes dated before legacyCutoff', (t) => {
    const body = PROPOSED.replace('## Alternatives considered\n\n**Skip it.** The format gate then has nothing to check.\n', '<!-- agent-note-format: alternatives-not-recorded (pre-format Agent Note) -->\n')
    const old = '.agents/notes/proposed/feature/2026-06-01-old.md'
    const fx = makeRepo({
      [old]: body,
      '.tianshu/config.json': '{"agentNotes":{"legacyCutoff":"2026-07-05"}}',
    })
    t.after(() => fx.cleanup())
    assert.deepEqual(agentNoteFormat.run(fx.ctx(), []), [])
  })

  it('passes a repository without an Agent Note tree and says so', (t) => {
    const fx = makeRepo({ 'README.md': '# Hi\n' })
    t.after(() => fx.cleanup())
    const ctx = fx.ctx()
    assert.deepEqual(agentNoteFormat.run(ctx, []), [])
    assert.ok(ctx.notices.some(notice => notice.includes('.agents/notes not found')))
  })

  it('under --staged reports only staged notes', (t) => {
    const bad = PROPOSED.replace('## Risks\n\nNone.\n', '')
    const fx = makeRepo({ 'README.md': '# Hi\n' })
    t.after(() => fx.cleanup())
    fx.write('.agents/notes/proposed/feature/2026-10-30-staged.md', bad)
    fx.stage('.agents/notes/proposed/feature/2026-10-30-staged.md')
    fx.write('.agents/notes/proposed/feature/2026-10-30-unstaged.md', bad)
    const out = agentNoteFormat.run(fx.ctx(true), [])
    assert.ok(out.length > 0)
    assert.ok(out.every(v => v.file === '.agents/notes/proposed/feature/2026-10-30-staged.md'))
  })
})
