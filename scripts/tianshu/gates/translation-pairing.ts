/** Adapted from deepseek-ai/deepseek-harness (MIT), scripts/verify-translation-pairing.ts. Corpus scope and exclusions come from .tianshu/config.json; `--cached` is replaced by `--staged`. */

import { mkdirSync, existsSync, readFileSync, writeFileSync } from 'node:fs'
import { basename, dirname, join } from 'node:path'
import { parseMarkdown } from '../lib/markdown.ts'
import { violation, type Ctx, type Gate, type Violation } from '../lib/context.ts'
import {
  hasLanguageSwitcher,
  normalizeTranslationMarkdownLinkEdits,
  translationLinkLocaleViolations,
  type TranslationLinkContext,
} from '../lib/translation-links.ts'
import {
  computePairingRecord,
  generatedRegions,
  pairPaths,
  parsePairingRecord,
  pairingRecordDiff,
  renderPairingRecord,
  structureDiff,
  structureSignature,
  switcherFor,
  switcherPattern,
  type PairingLinkBase,
} from '../lib/translation-pairing.ts'

const ARCHIVE_EXCLUDE = ['.agents/notes/archived/**']
/** Root-level documents that are paired like DSH's CONTRIBUTING / BRAND_GUIDELINES / SAFETY. */
const ROOT_PAIRED_DOCUMENTS = new Set(['CONTRIBUTING.md', 'SAFETY.md', 'BRAND_GUIDELINES.md'])

type TranslationConfig = Ctx['config']['translation']
const startsOrEquals = (file: string, entry: string): boolean => (entry.endsWith('/') ? file.startsWith(entry) : file === entry)

/**
 * DSH scope (every README, root documents, `.agents/notes/`, `docs/`) plus `translation.include`, minus `translation.exclude`.
 * Under a `translation.roots` prefix (a vendored project tree) the scope applies to the path below that prefix.
 */
function isExcludedFromPairing(file: string, cfg: TranslationConfig): boolean {
  if (cfg.exclude.some(entry => startsOrEquals(file, entry))) return true
  // AGENTS.md files are agent instructions, not reader documentation; DSH keeps them single-language.
  if (/(^|\/)AGENTS\.md$/.test(file)) return true
  const root = cfg.roots.find(prefix => file.startsWith(prefix))
  const rel = root === undefined ? file : file.slice(root.length)
  const inCorpus = /(^|\/)readme\.md$/i.test(rel) || ROOT_PAIRED_DOCUMENTS.has(rel) || rel.startsWith('.agents/notes/') || rel.startsWith('docs/')
    || cfg.include.some(entry => startsOrEquals(rel, entry))
  return !inCorpus
}

/** Normalize one CLI argument to its source anchor path; any file of the pair or the bare stem names the same pair. */
function anchorOf(argument: string, suffix: string): string {
  const normalized = argument.split('\\').join('/').replace(/^\.\//, '')
  if (normalized.endsWith(suffix)) return `${normalized.slice(0, -suffix.length)}.md`
  if (normalized.endsWith('.i18n.yaml')) return `${normalized.slice(0, -'.i18n.yaml'.length)}.md`
  if (normalized.endsWith('.md')) return normalized
  return `${normalized}.md`
}

interface Request {
  write: boolean
  all: boolean
  anchors: string[]
}

function parseArgs(args: string[], suffix: string): Request {
  const flags = args.filter(argument => argument.startsWith('--'))
  const anchors = [...new Set(args.filter(argument => !argument.startsWith('--')).map(argument => anchorOf(argument, suffix)))].sort()
  const unknown = flags.filter(flag => flag !== '--write' && flag !== '--all')
  if (unknown.length > 0) throw new Error(`unknown flag(s): ${unknown.join(', ')}`)
  const write = flags.includes('--write')
  const all = flags.includes('--all')
  if (all && !write) throw new Error('--all only applies to --write')
  if (write && all && anchors.length > 0) throw new Error('--write takes either pair paths or --all, not both')
  if (write && !all && anchors.length === 0) {
    throw new Error('--write requires the pair(s) you confirmed, or --all; recording pairs you did not review blesses unconfirmed content')
  }
  return { write, all, anchors }
}

/** Record the hashes of the named pairs (or every complete pair with --all) into their `.i18n.yaml` files. */
function writeRecords(ctx: Ctx, req: Request, candidates: string[], base: PairingLinkBase, suffix: string): Violation[] {
  if (!req.all) {
    for (const anchor of req.anchors) {
      if (!candidates.includes(anchor)) throw new Error(`${anchor} names no source document on disk`)
    }
  }
  const isExcluded = (file: string): boolean => isExcludedFromPairing(file, ctx.config.translation)
  const targets = req.all ? candidates : req.anchors
  for (const source of targets) {
    const paths = pairPaths(source, suffix)
    if (isExcluded(source)) {
      if (!req.all) throw new Error(`${source} is excluded from pairing (translation.exclude)`)
      continue
    }
    if (!ctx.exists(source) || !ctx.exists(paths.counterpart)) {
      if (!req.all) throw new Error(`cannot record ${source}: missing ${ctx.exists(source) ? paths.counterpart : source}`)
      continue
    }
    const en = ctx.text(source) ?? ''
    const zh = ctx.text(paths.counterpart) ?? ''
    let rendered: string
    try {
      const trees = { en: parseMarkdown(en), zh: parseMarkdown(zh) }
      rendered = renderPairingRecord(paths, computePairingRecord(paths, en, zh, base, trees), ctx.config.translation.roots)
    } catch (error) {
      throw new Error(`cannot record ${source}: ${error instanceof Error ? error.message : String(error)}`)
    }
    const target = join(ctx.root, paths.meta)
    if (existsSync(target) && readFileSync(target, 'utf8') === rendered) continue
    mkdirSync(dirname(target), { recursive: true })
    writeFileSync(target, rendered)
    ctx.notice(`recorded ${paths.meta}`)
  }
  return []
}

export const translationPairing: Gate = {
  name: 'translation-pairing',
  summary: 'bilingual pairs: both sides, matching structure, recorded section hashes, language switchers',
  runAll: true,
  run(ctx, args) {
    const cfg = ctx.config.translation
    if (!cfg.enabled) {
      ctx.notice('translation-pairing disabled (translation.enabled is false in .tianshu/config.json); skipped')
      return []
    }
    const suffix = `.${cfg.counterpartLanguage}.md`
    const req = parseArgs(args, suffix)
    if (req.write && ctx.staged) throw new Error('--write cannot be combined with --staged')
    const isCounterpart = (file: string): boolean => file.endsWith(suffix)
    const isExcluded = (file: string): boolean => isExcludedFromPairing(file, cfg)

    const files = ctx.list(['**/*.md', '**/*.i18n.yaml'], ARCHIVE_EXCLUDE)
    const fileSet = new Set(files)
    const candidates = files.filter(file => file.endsWith('.md') && !isCounterpart(file))
    const base: PairingLinkBase = {
      isPairSource: path => fileSet.has(path) && path.endsWith('.md') && !isCounterpart(path) && !isExcluded(path),
      exists: path => ctx.exists(path),
      counterpartSuffix: suffix,
      roots: cfg.roots,
    }
    if (req.write) return writeRecords(ctx, req, candidates, base, suffix)

    const scope = req.anchors.length > 0 ? new Set(req.anchors) : undefined
    const pattern = switcherPattern(cfg.sourceLanguage, cfg.counterpartLanguage)
    const out: Violation[] = []
    const report = (anchor: string, file: string, message: string, line = 0): void => {
      const { source, counterpart, meta } = pairPaths(anchor, suffix)
      if (ctx.staged && ![source, counterpart, meta].some(path => ctx.inScope(path))) return
      out.push(violation(file, line, 'translation-pairing', message))
    }

    // 1. Every in-scope source must have its counterpart.
    for (const source of candidates) {
      if (isExcluded(source) || (scope !== undefined && !scope.has(source))) continue
      const { counterpart } = pairPaths(source, suffix)
      if (!ctx.exists(counterpart)) {
        report(source, source, `in-scope documentation must merge bilingual; add ${counterpart} and record the pair`)
      }
    }

    // 2. Every pair that exists at all is complete, consistent, and structurally aligned.
    const anchors = new Set<string>()
    for (const file of files) {
      if (isCounterpart(file)) anchors.add(`${file.slice(0, -suffix.length)}.md`)
      else if (file.endsWith('.i18n.yaml')) anchors.add(`${file.slice(0, -'.i18n.yaml'.length)}.md`)
    }
    for (const anchor of [...anchors].sort()) {
      if (scope !== undefined && !scope.has(anchor)) continue
      const paths = pairPaths(anchor, suffix)
      const have = {
        source: ctx.exists(paths.source),
        counterpart: ctx.exists(paths.counterpart),
        meta: ctx.exists(paths.meta),
      }
      if (isExcluded(anchor)) {
        if (have.counterpart) report(anchor, paths.counterpart, `${anchor} is excluded from pairing; this translation must not exist`)
        if (have.meta) report(anchor, paths.meta, `${anchor} is excluded from pairing; this consistency record must not exist`)
        continue
      }
      const missing = [
        have.source ? undefined : paths.source,
        have.counterpart ? undefined : paths.counterpart,
        have.meta ? undefined : paths.meta,
      ].filter((path): path is string => path !== undefined)
      if (missing.length > 0) {
        report(anchor, anchor, `incomplete pair — missing ${missing.join(', ')} (pairs merge whole: both languages plus the .i18n.yaml record)`)
        continue
      }

      const enText = ctx.text(paths.source) ?? ''
      const zhText = ctx.text(paths.counterpart) ?? ''
      const metaText = ctx.text(paths.meta) ?? ''
      const record = parsePairingRecord(metaText)
      if (record === undefined) {
        report(anchor, paths.meta, 'malformed consistency record (expected `/<section path>:` entries, each followed by `  en: <16-hex>` and `  zh: <16-hex>`)')
        continue
      }

      let enTree: ReturnType<typeof parseMarkdown>
      let zhTree: ReturnType<typeof parseMarkdown>
      let current: ReturnType<typeof computePairingRecord>
      try {
        enTree = parseMarkdown(enText)
        zhTree = parseMarkdown(zhText)
        current = computePairingRecord(paths, enText, zhText, base, { en: enTree, zh: zhTree })
      } catch (error) {
        report(anchor, paths.source, `${paths.source} ↔ ${paths.counterpart}: ${error instanceof Error ? error.message : String(error)}`)
        continue
      }
      const recordErrors = pairingRecordDiff(record, current).map(message => (
        `out of sync — ${message} (bring the other side along, then re-record with --write)`
      ))
      if (recordErrors.length === 0 && renderPairingRecord(paths, current, cfg.roots) !== metaText) {
        recordErrors.push('not in canonical form (re-record with --write)')
      }
      if (recordErrors.length > 0) {
        for (const message of recordErrors) report(anchor, paths.meta, message)
        continue
      }

      const sourceSwitcher = switcherFor(paths.counterpart, cfg.repositoryBlobRoot, pattern)
      const counterpartSwitcher = switcherFor(paths.source, cfg.repositoryBlobRoot, pattern)
      const sourceContext: TranslationLinkContext = { ...base, sourcePath: paths.source }
      const counterpartContext: TranslationLinkContext = { ...base, sourcePath: paths.counterpart }
      for (const violating of [
        ...translationLinkLocaleViolations(enText, sourceContext, sourceSwitcher, enTree),
        ...translationLinkLocaleViolations(zhText, counterpartContext, counterpartSwitcher, zhTree),
      ]) {
        report(anchor, violating.sourcePath, `link target ${JSON.stringify(violating.url)} uses the wrong locale; expected ${JSON.stringify(violating.expectedUrl)}`, violating.line)
      }

      // Generated regions must match byte-for-byte once paired-document locale paths are normalized.
      let enRegions: string[]
      let zhRegions: string[]
      try {
        enRegions = generatedRegions(enText).map(region => normalizeTranslationMarkdownLinkEdits(region.text, sourceContext, undefined).content)
        zhRegions = generatedRegions(zhText).map(region => normalizeTranslationMarkdownLinkEdits(region.text, counterpartContext, undefined).content)
      } catch (error) {
        report(anchor, paths.source, `${paths.source} ↔ ${paths.counterpart}: ${error instanceof Error ? error.message : String(error)}`)
        continue
      }
      if (enRegions.length !== zhRegions.length || enRegions.some((region, index) => region !== zhRegions[index])) {
        report(anchor, paths.source, `${paths.source} ↔ ${paths.counterpart}: generated regions differ beyond paired-document locale paths; regenerate both sides`)
      }

      if (!hasLanguageSwitcher(zhTree, zhText, counterpartSwitcher)) {
        report(anchor, paths.counterpart, `missing language switcher — no link to ${basename(paths.source)}`)
      }
      if (!hasLanguageSwitcher(enTree, enText, sourceSwitcher)) {
        report(anchor, paths.source, `missing language switcher — no link back to ${basename(paths.counterpart)}`)
      }

      const enSignature = structureSignature(enTree, enText, sourceSwitcher, sourceContext)
      const zhSignature = structureSignature(zhTree, zhText, counterpartSwitcher, counterpartContext)
      for (const divergence of structureDiff(enSignature, zhSignature)) {
        report(anchor, paths.source, `${paths.source} ↔ ${paths.counterpart}: ${divergence}`)
      }
    }
    return out
  },
}
