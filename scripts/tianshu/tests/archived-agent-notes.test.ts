import assert from 'node:assert/strict'
import { describe, it } from 'node:test'
import { gitBlobHash } from '../lib/archive.ts'
import { archivedAgentNotes, ARCHIVE_MANIFEST } from '../gates/archived-agent-notes.ts'
import { makeRepo } from './helpers.ts'

const ARCHIVE = '.agents/notes/archived/feature'
const BASE = '2026-10-01-topic'

function triplet(suffix = 'English'): Record<string, string> {
  const en = `# Agent Note: Topic\n\nStatus: implemented\nArchived: 2026-10-30\n\n## Problem\n\nOld ${suffix}.\n`
  const zh = `# Agent Note: 主题\n\nStatus: implemented\nArchived: 2026-10-30\n\n## Problem\n\n旧内容。\n`
  const meta = `${BASE}.md: ${gitBlobHash(Buffer.from(en))}\n${BASE}.zh.md: ${gitBlobHash(Buffer.from(zh))}\n`
  return {
    [`${ARCHIVE}/${BASE}.md`]: en,
    [`${ARCHIVE}/${BASE}.zh.md`]: zh,
    [`${ARCHIVE}/${BASE}.i18n.yaml`]: meta,
  }
}

describe('archived-agent-notes', () => {
  it('passes when the archive is absent', (t) => {
    const fx = makeRepo({ 'README.md': '# Hi\n' })
    t.after(() => fx.cleanup())
    assert.deepEqual(archivedAgentNotes.run(fx.ctx(), []), [])
  })

  it('accepts a .gitkeep placeholder at the archive root', (t) => {
    const fx = makeRepo({ '.agents/notes/archived/.gitkeep': '', '.agents/notes/archived/AGENTS.md': '# Archive\n' })
    t.after(() => fx.cleanup())
    assert.deepEqual(archivedAgentNotes.run(fx.ctx(), []), [])
  })

  it('still rejects other root files in the archive', (t) => {
    const fx = makeRepo({ '.agents/notes/archived/stray.md': '# Stray\n', '.agents/notes/archived/AGENTS.md': '# Archive\n' })
    t.after(() => fx.cleanup())
    assert.ok(archivedAgentNotes.run(fx.ctx(), []).some(v => v.message.includes('unexpected root file')))
  })

  it('requires a manifest once artifacts exist', (t) => {
    const fx = makeRepo({ ...triplet(), ['.agents/notes/archived/AGENTS.md']: '# Archive\n' })
    t.after(() => fx.cleanup())
    assert.ok(archivedAgentNotes.run(fx.ctx(), []).some(v => v.message.includes('manifest is required')))
  })

  it('seals artifacts with --write and then passes the check', (t) => {
    const fx = makeRepo({ ...triplet(), ['.agents/notes/archived/AGENTS.md']: '# Archive\n' })
    t.after(() => fx.cleanup())
    assert.deepEqual(archivedAgentNotes.run(fx.ctx(), ['--write']), [])
    assert.deepEqual(archivedAgentNotes.run(fx.ctx(), []), [])
    assert.ok(fx.ctx().text(ARCHIVE_MANIFEST)?.includes(`${BASE}.md`))
  })

  it('reports a sealed artifact whose content changed', (t) => {
    const files = { ...triplet(), ['.agents/notes/archived/AGENTS.md']: '# Archive\n' }
    const fx = makeRepo(files)
    t.after(() => fx.cleanup())
    archivedAgentNotes.run(fx.ctx(), ['--write'])
    fx.write(`${ARCHIVE}/${BASE}.md`, `# Agent Note: Topic\n\nStatus: implemented\nArchived: 2026-10-30\n\n## Problem\n\nEdited.\n`)
    const out = archivedAgentNotes.run(fx.ctx(), [])
    assert.ok(out.some(v => v.message.includes('sealed content hash changed')))
  })

  it('reports an incomplete triplet', (t) => {
    const files = triplet()
    delete files[`${ARCHIVE}/${BASE}.zh.md`]
    const fx = makeRepo({ ...files, ['.agents/notes/archived/AGENTS.md']: '# Archive\n' })
    t.after(() => fx.cleanup())
    assert.ok(archivedAgentNotes.run(fx.ctx(), []).some(v => v.message.includes('incomplete archived triplet')))
  })

  it('reports an archive date earlier than the note filename date', (t) => {
    const files = triplet()
    const early = files[`${ARCHIVE}/${BASE}.md`]?.replace('Archived: 2026-10-30', 'Archived: 2026-09-01') ?? ''
    const zhEarly = files[`${ARCHIVE}/${BASE}.zh.md`]?.replace('Archived: 2026-10-30', 'Archived: 2026-09-01') ?? ''
    const meta = `${BASE}.md: ${gitBlobHash(Buffer.from(early))}\n${BASE}.zh.md: ${gitBlobHash(Buffer.from(zhEarly))}\n`
    const fx = makeRepo({
      [`${ARCHIVE}/${BASE}.md`]: early,
      [`${ARCHIVE}/${BASE}.zh.md`]: zhEarly,
      [`${ARCHIVE}/${BASE}.i18n.yaml`]: meta,
      ['.agents/notes/archived/AGENTS.md']: '# Archive\n',
    })
    t.after(() => fx.cleanup())
    assert.ok(archivedAgentNotes.run(fx.ctx(), []).some(v => v.message.includes('predates the note filename')))
  })

  it('reports an unknown kind folder', (t) => {
    const fx = makeRepo({ '.agents/notes/archived/refactor/2026-10-01-topic.md': '# x\n', ['.agents/notes/archived/AGENTS.md']: '# A\n' })
    t.after(() => fx.cleanup())
    assert.ok(archivedAgentNotes.run(fx.ctx(), []).some(v => v.message.includes('unknown Agent Note kind')))
  })

  it('refuses --write under --staged', (t) => {
    const fx = makeRepo({ 'README.md': '# Hi\n' })
    t.after(() => fx.cleanup())
    assert.throws(() => archivedAgentNotes.run(fx.ctx(true), ['--write']), /--write cannot be combined with --staged/)
  })
})
