import assert from 'node:assert/strict'
import { describe, it } from 'node:test'
import { docBudgets } from '../gates/doc-budgets.ts'
import { makeRepo } from './helpers.ts'

const words = (count: number): string => Array.from({ length: count }, () => 'word').join(' ')

describe('doc-budgets', () => {
  it('passes with a notice when no manifest exists', (t) => {
    const fx = makeRepo({ 'README.md': words(5) })
    t.after(() => fx.cleanup())
    const ctx = fx.ctx()
    assert.deepEqual(docBudgets.run(ctx, []), [])
    assert.ok(ctx.notices.some(notice => notice.includes('doc-budgets.json not found')))
  })

  it('passes a document under its ceiling', (t) => {
    const fx = makeRepo({ 'README.md': words(5), '.tianshu/doc-budgets.json': '{"README.md": 5}' })
    t.after(() => fx.cleanup())
    assert.deepEqual(docBudgets.run(fx.ctx(), []), [])
  })

  it('reports a document over its ceiling', (t) => {
    const fx = makeRepo({ 'README.md': words(6), '.tianshu/doc-budgets.json': '{"README.md": 5}' })
    t.after(() => fx.cleanup())
    const out = docBudgets.run(fx.ctx(), [])
    assert.equal(out.length, 1)
    assert.equal(out[0]?.file, 'README.md')
    assert.match(out[0]?.message ?? '', /6 words exceeds the 5-word ceiling/)
  })

  it('reports a budgeted file that does not exist', (t) => {
    const fx = makeRepo({ '.tianshu/doc-budgets.json': '{"docs/gone.md": 10}' })
    t.after(() => fx.cleanup())
    assert.ok(docBudgets.run(fx.ctx(), []).some(v => v.message.includes('does not exist')))
  })

  it('reports a non-positive or non-integer ceiling', (t) => {
    const fx = makeRepo({ 'README.md': 'x', '.tianshu/doc-budgets.json': '{"README.md": 0, "AGENTS.md": "5"}' })
    t.after(() => fx.cleanup())
    const out = docBudgets.run(fx.ctx(), [])
    assert.equal(out.filter(v => v.message.includes('positive integer')).length, 2)
  })

  it('reports invalid JSON in the manifest', (t) => {
    const fx = makeRepo({ '.tianshu/doc-budgets.json': '{not json' })
    t.after(() => fx.cleanup())
    assert.ok(docBudgets.run(fx.ctx(), []).some(v => v.message.startsWith('invalid JSON')))
  })

  it('under --staged reports only an over-ceiling document that is staged', (t) => {
    const fx = makeRepo({ 'README.md': words(2), 'docs.md': 'x', '.tianshu/doc-budgets.json': '{"README.md": 1, "docs.md": 1}' })
    t.after(() => fx.cleanup())
    fx.write('README.md', words(9))
    fx.stage('README.md')
    const out = docBudgets.run(fx.ctx(true), [])
    assert.deepEqual(out.map(v => v.file), ['README.md'])
  })
})
