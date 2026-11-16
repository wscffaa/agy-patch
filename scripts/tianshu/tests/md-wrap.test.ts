import assert from 'node:assert/strict'
import { describe, it } from 'node:test'
import { mdWrap } from '../gates/md-wrap.ts'
import { makeRepo } from './helpers.ts'

describe('md-wrap', () => {
  it('passes one-line paragraphs, lists, and code blocks', (t) => {
    const fx = makeRepo({
      'README.md': '# Title\n\nOne physical line of prose.\n\n- item one\n- item two\n\n```text\nline a\nline b\n```\n',
    })
    t.after(() => fx.cleanup())
    assert.deepEqual(mdWrap.run(fx.ctx(), []), [])
  })

  it('reports a hard-wrapped paragraph at its first line', (t) => {
    const fx = makeRepo({ 'docs/a.md': '# A\n\nFirst half of the sentence\nsecond half.\n' })
    t.after(() => fx.cleanup())
    const out = mdWrap.run(fx.ctx(), [])
    assert.equal(out.length, 1)
    assert.equal(out[0]?.file, 'docs/a.md')
    assert.equal(out[0]?.line, 3)
  })

  it('ignores YAML frontmatter', (t) => {
    const fx = makeRepo({ 'docs/a.md': '---\ntitle: A\nlayout: doc\n---\n\n# A\n\nOne line.\n' })
    t.after(() => fx.cleanup())
    assert.deepEqual(mdWrap.run(fx.ctx(), []), [])
  })

  it('passes a repository with no Markdown', (t) => {
    const fx = makeRepo({ 'main.ts': 'export {}\n' })
    t.after(() => fx.cleanup())
    assert.deepEqual(mdWrap.run(fx.ctx(), []), [])
  })

  it('under --staged reports only staged documents', (t) => {
    const fx = makeRepo({ 'a.md': '# A\n\nOne line.\n' })
    t.after(() => fx.cleanup())
    fx.write('b.md', '# B\n\nwrapped\ntext.\n')
    fx.stage('b.md')
    fx.write('c.md', '# C\n\nwrapped\ntext.\n')
    assert.deepEqual(mdWrap.run(fx.ctx(true), []).map(v => v.file), ['b.md'])
  })
})
