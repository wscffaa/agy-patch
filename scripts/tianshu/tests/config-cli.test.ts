import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { resolve } from 'node:path'
import { describe, it } from 'node:test'
import { loadConfig } from '../lib/config.ts'
import { Ctx, globToRegExp } from '../lib/context.ts'
import { makeRepo } from './helpers.ts'

const CLI = resolve(import.meta.dirname, '../cli.ts')

function runCli(args: string[]): number {
  const result = spawnSync(process.execPath, ['--import', 'tsx', CLI, ...args], { encoding: 'utf8' })
  return result.status ?? -1
}

describe('config', () => {
  it('falls back to defaults with a notice when config.json is missing', (t) => {
    const fx = makeRepo({ 'README.md': '# Hi\n' })
    t.after(() => fx.cleanup())
    const loaded = loadConfig(fx.root)
    assert.equal(loaded.config.translation.enabled, false)
    assert.equal(loaded.notices.length, 1)
  })

  it('rejects invalid JSON', (t) => {
    const fx = makeRepo({ '.tianshu/config.json': '{nope' })
    t.after(() => fx.cleanup())
    assert.throws(() => loadConfig(fx.root), /invalid JSON/)
  })

  it('rejects a non-string entry in an exclude list', (t) => {
    const fx = makeRepo({ '.tianshu/config.json': '{"scope":{"exclude":[1]}}' })
    t.after(() => fx.cleanup())
    assert.throws(() => loadConfig(fx.root), /scope.exclude must be an array of strings/)
  })
})

describe('glob matching', () => {
  it('matches nested and dot-directory Markdown but not other extensions', () => {
    const re = globToRegExp('**/*.md')
    assert.ok(re.test('README.md'))
    assert.ok(re.test('docs/a/b.md'))
    assert.ok(re.test('.agents/notes/proposed/feature/x.md'))
    assert.ok(!re.test('docs/a.txt'))
  })
})

describe('Ctx', () => {
  it('refuses --staged outside a Git repository', (t) => {
    const fx = makeRepo({ 'README.md': '# Hi\n' }, { git: false })
    t.after(() => fx.cleanup())
    assert.throws(() => new Ctx(fx.root, true), /Git repository/)
  })
})

describe('cli exit codes', () => {
  it('exits 0 for a clean repository', (t) => {
    const fx = makeRepo({ 'README.md': '# Hi\n\nBody line.\n' })
    t.after(() => fx.cleanup())
    assert.equal(runCli(['gates', '--repo', fx.root]), 0)
  })

  it('exits 1 when a gate reports a violation', (t) => {
    const fx = makeRepo({ 'README.md': '# Hi\n\n[gone](missing.md)\n' })
    t.after(() => fx.cleanup())
    assert.equal(runCli(['gates', '--repo', fx.root]), 1)
  })

  it('exits 2 for an unknown gate name', (t) => {
    const fx = makeRepo({ 'README.md': '# Hi\n' })
    t.after(() => fx.cleanup())
    assert.equal(runCli(['gate', 'no-such-gate', '--repo', fx.root]), 2)
  })
})
