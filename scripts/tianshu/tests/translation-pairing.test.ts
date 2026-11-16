import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, it } from 'node:test'
import { translationPairing } from '../gates/translation-pairing.ts'
import { makeRepo } from './helpers.ts'

const CONFIG = JSON.stringify({ translation: { enabled: true } })
const EN = '# Sample\n\nEnglish | [中文](README.zh.md)\n\n## Usage\n\nRun it.\n'
const ZH = '# 示例\n\n[English](README.md) | 中文\n\n## 用法\n\n运行它。\n'
const ZH_NO_SWITCHER = '# 示例\n\n## 用法\n\n运行它。\n'

describe('translation-pairing', () => {
  it('is skipped with a notice when translation.enabled is not set', (t) => {
    const fx = makeRepo({ 'README.md': EN })
    t.after(() => fx.cleanup())
    const ctx = fx.ctx()
    assert.deepEqual(translationPairing.run(ctx, []), [])
    assert.ok(ctx.notices.some(notice => notice.includes('disabled')))
  })

  it('passes a complete pair once its record is written', (t) => {
    const fx = makeRepo({ 'README.md': EN, 'README.zh.md': ZH, '.tianshu/config.json': CONFIG })
    t.after(() => fx.cleanup())
    assert.deepEqual(translationPairing.run(fx.ctx(), ['--write', '--all']), [])
    assert.deepEqual(translationPairing.run(fx.ctx(), []), [])
  })

  it('reports a source document without its counterpart', (t) => {
    const fx = makeRepo({ 'README.md': EN, '.tianshu/config.json': CONFIG })
    t.after(() => fx.cleanup())
    const out = translationPairing.run(fx.ctx(), [])
    assert.ok(out.some(v => v.file === 'README.md' && v.message.includes('must merge bilingual')))
  })

  it('reports a complete-looking pair that lacks its consistency record', (t) => {
    const fx = makeRepo({ 'README.md': EN, 'README.zh.md': ZH, '.tianshu/config.json': CONFIG })
    t.after(() => fx.cleanup())
    assert.ok(translationPairing.run(fx.ctx(), []).some(v => v.message.includes('incomplete pair')))
  })

  it('reports a recorded section changed on one side only', (t) => {
    const fx = makeRepo({ 'README.md': EN, 'README.zh.md': ZH, '.tianshu/config.json': CONFIG })
    t.after(() => fx.cleanup())
    translationPairing.run(fx.ctx(), ['--write', '--all'])
    fx.write('README.zh.md', ZH.replace('运行它。', '运行它两次。'))
    assert.ok(translationPairing.run(fx.ctx(), []).some(v => v.message.includes('changed since confirmation (zh)')))
  })

  it('reports a counterpart without a language switcher', (t) => {
    const fx = makeRepo({ 'README.md': EN, 'README.zh.md': ZH_NO_SWITCHER, '.tianshu/config.json': CONFIG })
    t.after(() => fx.cleanup())
    translationPairing.run(fx.ctx(), ['--write', '--all'])
    assert.ok(translationPairing.run(fx.ctx(), []).some(v => v.message.includes('missing language switcher')))
  })

  it('refuses --write without named pairs or --all', (t) => {
    const fx = makeRepo({ 'README.md': EN, 'README.zh.md': ZH, '.tianshu/config.json': CONFIG })
    t.after(() => fx.cleanup())
    assert.throws(() => translationPairing.run(fx.ctx(), ['--write']), /--write requires/)
  })

  it('under --staged reports only a pair with a staged file', (t) => {
    const fx = makeRepo({ 'other.md': '# Other\n', '.tianshu/config.json': CONFIG })
    t.after(() => fx.cleanup())
    fx.write('README.md', EN)
    fx.stage('README.md')
    const out = translationPairing.run(fx.ctx(true), [])
    assert.ok(out.length > 0)
    assert.ok(out.every(v => v.file === 'README.md'))
  })

  it('does not require a counterpart for documents outside the DSH corpus', (t) => {
    const fx = makeRepo({ 'skills/x/SKILL.md': '# Skill\n\nBody.\n', '.github/pull_request_template.md': '# PR\n', '.tianshu/config.json': CONFIG })
    t.after(() => fx.cleanup())
    assert.deepEqual(translationPairing.run(fx.ctx(), []), [])
  })

  it('requires counterparts for docs/ and .agents/notes/ documents', (t) => {
    const fx = makeRepo({
      'docs/a.md': '# A\n', '.agents/notes/proposed/process/2026-10-30-x.md': '# Agent Note: X\n',
      '.tianshu/config.json': CONFIG,
    })
    t.after(() => fx.cleanup())
    const files = translationPairing.run(fx.ctx(), []).map(v => v.file).sort()
    assert.deepEqual(files, ['.agents/notes/proposed/process/2026-10-30-x.md', 'docs/a.md'])
  })

  it('pairs extra paths named in translation.include', (t) => {
    const cfg = JSON.stringify({ translation: { enabled: true, include: ['skills/'] } })
    const fx = makeRepo({ 'skills/x/SKILL.md': '# Skill\n\nBody.\n', '.tianshu/config.json': cfg })
    t.after(() => fx.cleanup())
    assert.deepEqual(translationPairing.run(fx.ctx(), []).map(v => v.file), ['skills/x/SKILL.md'])
  })

  it('applies the corpus scope below a configured root', (t) => {
    const cfg = JSON.stringify({ translation: { enabled: true, roots: ['kit/template/'] } })
    const fx = makeRepo({ 'kit/template/docs/a.md': '# A\n', 'kit/template/AGENTS.md': '# Rules\n', '.tianshu/config.json': cfg })
    t.after(() => fx.cleanup())
    assert.deepEqual(translationPairing.run(fx.ctx(), []).map(v => v.file), ['kit/template/docs/a.md'])
  })

  it('keeps records written under a configured root valid once the tree lands at a project root', (t) => {
    const docs = {
      'docs/a.md': '# A\n\nEnglish | [中文](a.zh.md)\n\nSee [B](b.md).\n',
      'docs/a.zh.md': '# A\n\n[English](a.md) | 中文\n\n见 [B](b.zh.md)。\n',
      'docs/b.md': '# B\n\nEnglish | [中文](b.zh.md)\n\nBody.\n',
      'docs/b.zh.md': '# B\n\n[English](b.md) | 中文\n\n正文。\n',
    }
    const kitCfg = JSON.stringify({ translation: { enabled: true, roots: ['kit/template/'] } })
    const kit = makeRepo({
      ...Object.fromEntries(Object.entries(docs).map(([rel, text]) => [`kit/template/${rel}`, text])),
      '.tianshu/config.json': kitCfg,
    })
    t.after(() => kit.cleanup())
    assert.deepEqual(translationPairing.run(kit.ctx(), ['--write', '--all']), [])
    assert.deepEqual(translationPairing.run(kit.ctx(), []), [])
    const landed: Record<string, string> = { ...docs, '.tianshu/config.json': CONFIG }
    for (const name of ['a', 'b']) {
      landed[`docs/${name}.i18n.yaml`] = readFileSync(join(kit.root, `kit/template/docs/${name}.i18n.yaml`), 'utf8')
    }
    const project = makeRepo(landed)
    t.after(() => project.cleanup())
    assert.deepEqual(translationPairing.run(project.ctx(), []), [])
  })

  it('does not treat root AGENTS.md or THIRD_PARTY_NOTICES.md as paired documents', (t) => {
    const fx = makeRepo({ 'AGENTS.md': '# Rules\n', 'THIRD_PARTY_NOTICES.md': '# Notices\n', '.tianshu/config.json': CONFIG })
    t.after(() => fx.cleanup())
    assert.deepEqual(translationPairing.run(fx.ctx(), []), [])
  })

  it('never pairs AGENTS.md files at any depth', (t) => {
    const fx = makeRepo({ 'docs/AGENTS.md': '# Rules\n', '.agents/notes/AGENTS.md': '# Rules\n', 'docs/a.md': '# A\n', '.tianshu/config.json': CONFIG })
    t.after(() => fx.cleanup())
    assert.deepEqual(translationPairing.run(fx.ctx(), []).map(v => v.file), ['docs/a.md'])
  })

  it('rejects a counterpart that exists for an AGENTS.md file', (t) => {
    const fx = makeRepo({ 'docs/AGENTS.md': '# Rules\n', 'docs/AGENTS.zh.md': '# 规则\n', '.tianshu/config.json': CONFIG })
    t.after(() => fx.cleanup())
    assert.ok(translationPairing.run(fx.ctx(), []).some(v => v.message.includes('excluded from pairing')))
  })
})
