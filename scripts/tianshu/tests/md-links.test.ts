import assert from 'node:assert/strict'
import { describe, it } from 'node:test'
import { githubSlug } from '../gates/md-links.ts'
import { mdLinks } from '../gates/md-links.ts'
import { makeRepo } from './helpers.ts'

describe('md-links', () => {
  it('passes relative links, same-file anchors, and existing fragments', (t) => {
    const fx = makeRepo({
      'README.md': '# Home\n\nSee [guide](docs/guide.md#setup-steps) and [top](#home).\n',
      'docs/guide.md': '# Guide\n\n## Setup Steps\n\nBody.\n',
    })
    t.after(() => fx.cleanup())
    assert.deepEqual(mdLinks.run(fx.ctx(), []), [])
  })

  it('reports a link whose target does not exist', (t) => {
    const fx = makeRepo({ 'README.md': '# Home\n\n[gone](docs/missing.md)\n' })
    t.after(() => fx.cleanup())
    const out = mdLinks.run(fx.ctx(), [])
    assert.equal(out.length, 1)
    assert.equal(out[0]?.file, 'README.md')
    assert.equal(out[0]?.line, 3)
    assert.match(out[0]?.message ?? '', /target does not exist/)
  })

  it('reports a fragment that names no heading in the target', (t) => {
    const fx = makeRepo({ 'README.md': '# Home\n\n[x](docs/guide.md#nope)\n', 'docs/guide.md': '# Guide\n' })
    t.after(() => fx.cleanup())
    assert.ok(mdLinks.run(fx.ctx(), []).some(v => v.message.includes('no such anchor')))
  })

  it('reports a same-file anchor that does not exist', (t) => {
    const fx = makeRepo({ 'README.md': '# Home\n\n[x](#missing)\n' })
    t.after(() => fx.cleanup())
    assert.ok(mdLinks.run(fx.ctx(), []).some(v => v.message.includes('no such anchor')))
  })

  it('ignores external, protocol-relative, and root-absolute targets', (t) => {
    const fx = makeRepo({ 'README.md': '# Home\n\n[a](https://example.com/x) [b](//cdn.example.com/y) [c](/docs/z.md)\n' })
    t.after(() => fx.cleanup())
    assert.deepEqual(mdLinks.run(fx.ctx(), []), [])
  })

  it('passes a repository with no Markdown', (t) => {
    const fx = makeRepo({ 'main.ts': 'export {}\n' })
    t.after(() => fx.cleanup())
    assert.deepEqual(mdLinks.run(fx.ctx(), []), [])
  })

  it('checks Markdown inside dot-directories such as .agents', (t) => {
    const fx = makeRepo({ '.agents/skills/a/SKILL.md': '# A\n\n[gone](missing.md)\n' })
    t.after(() => fx.cleanup())
    assert.equal(mdLinks.run(fx.ctx(), []).length, 1)
  })

  it('does not judge archived notes as sources', (t) => {
    const fx = makeRepo({ '.agents/notes/archived/feature/2026-10-01-x.md': '[gone](nowhere.md)\n' })
    t.after(() => fx.cleanup())
    assert.deepEqual(mdLinks.run(fx.ctx(), []), [])
  })

  it('under --staged reports only the staged document', (t) => {
    const fx = makeRepo({ 'README.md': '# Home\n', 'other.md': '# Other\n' })
    t.after(() => fx.cleanup())
    fx.write('other.md', '# Other\n\n[gone](nowhere.md)\n')
    fx.stage('other.md')
    fx.write('README.md', '# Home\n\n[gone](nowhere.md)\n')
    const out = mdLinks.run(fx.ctx(true), [])
    assert.deepEqual(out.map(v => v.file), ['other.md'])
  })

  it('computes GitHub-style slugs including repeats', () => {
    assert.equal(githubSlug('Hello, World!'), 'hello-world')
    assert.equal(githubSlug('web_fetch tool'), 'web_fetch-tool')
  })
})
