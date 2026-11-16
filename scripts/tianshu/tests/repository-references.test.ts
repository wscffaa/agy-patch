import assert from 'node:assert/strict'
import { describe, it } from 'node:test'
import { repositoryReferences, canonicalReferenceText, uniquePrefixMatch } from '../gates/repository-references.ts'
import { makeRepo } from './helpers.ts'

const configWith = (refs: Record<string, string[]>): string => JSON.stringify({ repositoryReferences: refs })

describe('repository-references', () => {
  it('passes a clean repository with decimal-only numbers', (t) => {
    const fx = makeRepo({ 'README.md': '# Version 1234567 released 2026-10-30\n' })
    t.after(() => fx.cleanup())
    assert.deepEqual(repositoryReferences.run(fx.ctx(), []), [])
  })

  it('reports a line naming a real commit by its abbreviated hash', (t) => {
    const fx = makeRepo({ 'README.md': '# Hi\n' })
    t.after(() => fx.cleanup())
    const commit = fx.git(['rev-parse', 'HEAD'])
    fx.write('CHANGELOG.md', `# Log\n\nFixed in ${commit.slice(0, 12)}.\n`)
    const out = repositoryReferences.run(fx.ctx(), [])
    assert.deepEqual(out.map(v => [v.file, v.line, v.rule]), [['CHANGELOG.md', 3, 'commit-hash']])
  })

  it('ignores an unknown hex-looking token with no matching object', (t) => {
    const fx = makeRepo({ 'README.md': '# Hi\n\nToken deadbeefcafe is not an object.\n' })
    t.after(() => fx.cleanup())
    assert.deepEqual(repositoryReferences.run(fx.ctx(), []), [])
  })

  it('reports a forbidden organization URL and honors an allowed prefix', (t) => {
    const fx = makeRepo({
      'README.md': '# Hi\n\nSee https://github.com/acme-old/tool and https://github.com/acme-old/kit-ok\n',
      '.tianshu/config.json': configWith({ forbiddenOrganizations: ['acme-old'], allowedUrlPrefixes: ['github.com/acme-old/kit-ok'] }),
    })
    t.after(() => fx.cleanup())
    const out = repositoryReferences.run(fx.ctx(), [])
    assert.deepEqual(out.map(v => v.rule), ['organization-url'])
  })

  it('treats an escaped organization URL as the same reference', (t) => {
    const fx = makeRepo({
      'README.md': '# Hi\n\nSee https%3A%2F%2Fgithub.com%2Facme-old%2Ftool\n',
      '.tianshu/config.json': configWith({ forbiddenOrganizations: ['acme-old'] }),
    })
    t.after(() => fx.cleanup())
    assert.ok(repositoryReferences.run(fx.ctx(), []).some(v => v.rule === 'organization-url'))
  })

  it('still checks organization URLs without a Git repository and says commit checks are skipped', (t) => {
    const fx = makeRepo({
      'README.md': '# Hi\n\nhttps://github.com/acme-old/x\n',
      '.tianshu/config.json': configWith({ forbiddenOrganizations: ['acme-old'] }),
    }, { git: false })
    t.after(() => fx.cleanup())
    const ctx = fx.ctx()
    const out = repositoryReferences.run(ctx, [])
    assert.deepEqual(out.map(v => v.rule), ['organization-url'])
    assert.ok(ctx.notices.some(notice => notice.includes('commit-hash check skipped')))
  })

  it('passes an empty repository with no commits', (t) => {
    const fx = makeRepo({ 'README.md': '# Hi\n' }, { commit: false })
    t.after(() => fx.cleanup())
    assert.deepEqual(repositoryReferences.run(fx.ctx(), []), [])
  })

  it('under --staged ignores commit references in unstaged files', (t) => {
    const fx = makeRepo({ 'README.md': '# Hi\n' })
    t.after(() => fx.cleanup())
    const commit = fx.git(['rev-parse', 'HEAD'])
    fx.write('NOTES.md', `# Notes\n\n${commit.slice(0, 10)}\n`)
    assert.deepEqual(repositoryReferences.run(fx.ctx(true), []), [])
  })

  it('canonicalizes escapes and compatibility characters', () => {
    assert.equal(canonicalReferenceText('https%3A%2F%2FGitHub.com'), 'https://github.com')
    assert.equal(canonicalReferenceText('git&hyphen;hub'), 'git-hub')
  })

  it('returns a prefix match only when it is unique', () => {
    assert.equal(uniquePrefixMatch(['aa11', 'bb22', 'bb23'], 'aa1'), 'aa11')
    assert.equal(uniquePrefixMatch(['bb22', 'bb23'], 'bb2'), undefined)
    assert.equal(uniquePrefixMatch([], 'bb2'), undefined)
  })
})
