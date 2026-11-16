/** Adapted from deepseek-ai/deepseek-harness (MIT), scripts/translation-pairing.ts and scripts/translation-pairing-record.ts. Pure helpers only. */

import { createHash } from 'node:crypto'
import { basename } from 'node:path'
import type { Nodes, RootContent } from 'mdast'
import { parseMarkdown } from './markdown.ts'
import {
  languageSwitcherLinkOffset,
  normalizeTranslationMarkdownLinkEdits,
  semanticTranslationLinkNodeTarget,
  type LinkNode,
  type SwitcherSpec,
  type TranslationLinkContext,
  type TranslationLinkDestinationEdit,
  type TranslationLinkNormalization,
} from './translation-links.ts'

/** Complete opening marker line: `<!-- BEGIN GENERATED <slug> -->`. */
const GENERATED_REGION_BEGIN_LINE = /^<!-- BEGIN GENERATED (\S+)(?: [^>]*)? -->$/
const GENERATED_REGION_END_LINE = /^<!-- END GENERATED (\S+) -->$/
const GENERATED_REGION_MARKER_HINT = /^<!-- (?:BEGIN|END) GENERATED /
const KEY_LINE = /^(\/[^\s:#]*):$/
const HASH_LINE = /^ {2}(en|zh): ([0-9a-f]{16})$/

/** The two paths of one bilingual pair plus its consistency record. */
export interface PairPaths {
  source: string
  counterpart: string
  meta: string
}

/** Content hashes of one section's translated blocks. */
export interface SectionHashes {
  en: string
  zh: string
}

/** Section key (English heading-slug path) to hashes, in document order. */
export type PairingRecord = ReadonlyMap<string, SectionHashes>

/** Link-resolution inputs shared by both sides of one pair. */
export type PairingLinkBase = Omit<TranslationLinkContext, 'sourcePath'>

/** Language labels used by the switcher paragraph. Unknown codes fall back to the code itself. */
const LANGUAGE_LABELS: Record<string, string> = { en: 'English', zh: '中文' }

/** Derive the three paths of a pair from its English document. */
export function pairPaths(source: string, counterpartSuffix: string): PairPaths {
  if (!source.endsWith('.md') || source.endsWith(counterpartSuffix)) {
    throw new Error(`expected a source Markdown path, received ${JSON.stringify(source)}`)
  }
  return {
    source,
    counterpart: `${source.slice(0, -3)}${counterpartSuffix}`,
    meta: `${source.slice(0, -3)}.i18n.yaml`,
  }
}

/** Accepted switcher targets on one side: the counterpart's basename and, when configured, its public blob URL. */
export function switcherTargets(counterpart: string, blobRoot: string | null): string[] {
  return [basename(counterpart), ...(blobRoot === null ? [] : [`${blobRoot}${counterpart}`])]
}

/** Matches `English | [中文](...)` on the source side and `[English](...) | 中文` on the counterpart side. */
export function switcherPattern(sourceLanguage: string, counterpartLanguage: string): RegExp {
  const source = LANGUAGE_LABELS[sourceLanguage] ?? sourceLanguage
  const counterpart = LANGUAGE_LABELS[counterpartLanguage] ?? counterpartLanguage
  const escaped = (text: string): string => text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  return new RegExp(`^(?:${escaped(source)} \\| \\[${escaped(counterpart)}\\]\\([^\\n]+\\)|\\[${escaped(source)}\\]\\([^\\n]+\\) \\| ${escaped(counterpart)})$`)
}

/** Switcher spec for one side: the accepted targets point at the other side. */
export function switcherFor(otherSide: string, blobRoot: string | null, pattern: RegExp): SwitcherSpec {
  return { accepted: switcherTargets(otherSide, blobRoot), pattern }
}

/** One generated region: its slug, zero-based marker line indices, and text. */
export interface GeneratedRegion {
  slug: string
  begin: number
  end: number
  text: string
}

/** Locate every generated region (`<!-- BEGIN/END GENERATED slug -->` line pairs). */
export function generatedRegions(content: string): GeneratedRegion[] {
  const lines = content.split('\n')
  const regions: GeneratedRegion[] = []
  let open: { slug: string; begin: number } | null = null
  for (const [index, line] of lines.entries()) {
    const begin = GENERATED_REGION_BEGIN_LINE.exec(line)
    if (begin?.[1]) {
      if (open) throw new Error('generated region BEGIN marker nested inside an open region')
      open = { slug: begin[1], begin: index }
      continue
    }
    const end = GENERATED_REGION_END_LINE.exec(line)
    if (end?.[1]) {
      if (!open) throw new Error('generated region END marker without a BEGIN')
      if (end[1] !== open.slug) throw new Error(`generated region END slug '${end[1]}' does not match its BEGIN slug '${open.slug}'`)
      regions.push({ ...open, end: index, text: lines.slice(open.begin, index + 1).join('\n') })
      open = null
      continue
    }
    if (GENERATED_REGION_MARKER_HINT.test(line)) {
      throw new Error(`malformed generated region marker line: ${JSON.stringify(line)}`)
    }
  }
  if (open) throw new Error('generated region BEGIN marker without an END')
  return regions
}

interface Section {
  heading?: Extract<Nodes, { type: 'heading' }>
  blocks: string[]
}

interface TopLevelBlock {
  node: RootContent
  start: number | undefined
  end: number | undefined
  line: number
}

function headingText(node: Nodes): string {
  if ('value' in node && (node.type === 'text' || node.type === 'inlineCode')) return node.value
  return 'children' in node ? node.children.map(headingText).join('') : ''
}

function topLevelBlocks(tree: Nodes): TopLevelBlock[] {
  if (tree.type !== 'root') throw new Error('Markdown parser returned a non-root tree')
  return tree.children.map(node => ({
    node,
    start: node.position?.start.offset,
    end: node.position?.end.offset,
    line: node.position?.start.line ?? 0,
  }))
}

/** Characters that read only as destination text in every destination slot. */
const PARSE_NEUTRAL_DESTINATION = /^[A-Za-z0-9._/:#%-]+$/

function isParseNeutralEdit(markdown: string, edit: TranslationLinkDestinationEdit): boolean {
  const authored = markdown.slice(edit.start, edit.end)
  const nodeStart = edit.node.position?.start.offset
  const nodeEnd = edit.node.position?.end.offset
  if (nodeStart === undefined || nodeEnd === undefined || edit.node.url !== authored) return false
  if (!PARSE_NEUTRAL_DESTINATION.test(authored) || !PARSE_NEUTRAL_DESTINATION.test(edit.value)) return false
  const before = markdown.slice(nodeStart, edit.start)
  const after = markdown.slice(edit.end, nodeEnd)
  const angle = before.endsWith('<')
  return edit.node.type === 'link'
    ? /\]\([ \t]*<?$/.test(before) && (angle ? /^>[ \t]*\)$/ : /^[ \t]*\)$/).test(after)
    : /\]:[ \t]*<?$/.test(before) && (angle ? /^>[ \t]*$/ : /^[ \t]*$/).test(after)
}

/**
 * Move the authored tree's top-level blocks to normalized offsets without reparsing, when every
 * edit is provably parse-neutral; otherwise undefined and the caller reparses.
 */
function normalizedTopLevelBlocks(markdown: string, tree: Nodes, edits: readonly TranslationLinkDestinationEdit[]): TopLevelBlock[] | undefined {
  if (!edits.every(edit => isParseNeutralEdit(markdown, edit))) return undefined
  let next = 0
  let shift = 0
  const moved: TopLevelBlock[] = []
  for (const block of topLevelBlocks(tree)) {
    if (block.start === undefined || block.end === undefined) return undefined
    const start = block.start + shift
    for (let edit = edits[next]; edit !== undefined && edit.start < block.end; edit = edits[next]) {
      if (edit.start < block.start || edit.end > block.end) return undefined
      shift += edit.value.length - (edit.end - edit.start)
      next += 1
    }
    moved.push({ ...block, start, end: block.end + shift })
  }
  return next === edits.length ? moved : undefined
}

/** Split normalized Markdown into the preamble plus one section per heading, skipping code blocks and generated regions. */
function sections(markdown: string, blocks: readonly TopLevelBlock[]): Section[] {
  const frontmatter = /^---\n[\s\S]*?\n---(?:\n|$)/.exec(markdown)?.[0].length ?? 0
  const result: Section[] = [{ blocks: frontmatter > 0 ? [markdown.slice(0, frontmatter)] : [] }]
  const regionLines = generatedRegions(markdown).map(region => [region.begin + 1, region.end + 1] as const)
  for (const { node, start, end, line } of blocks) {
    if ((start ?? 0) < frontmatter) continue
    if (node.type === 'heading') result.push({ heading: node, blocks: [] })
    if (node.type === 'code' || regionLines.some(([begin, regionEnd]) => line >= begin && line <= regionEnd)) continue
    result.at(-1)?.blocks.push(markdown.slice(start, end))
  }
  return result
}

function sideSections(markdown: string, normalized: TranslationLinkNormalization, tree: Nodes): Section[] {
  if (normalized.content === markdown) return sections(markdown, topLevelBlocks(tree))
  const moved = normalizedTopLevelBlocks(markdown, tree, normalized.edits)
  return sections(normalized.content, moved ?? topLevelBlocks(parseMarkdown(normalized.content)))
}

function slug(text: string): string {
  return text.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'section'
}

function sectionHash(blocks: string[]): string {
  return createHash('sha256').update(blocks.join('\n')).digest('hex').slice(0, 16)
}

/**
 * Compute the per-section record for one pair. Both sides split at every heading; section i of
 * one side corresponds to section i of the other. Sections with no remaining blocks have no entry.
 * @throws when the two sides have different heading counts, or a generated region is malformed.
 */
export function computePairingRecord(
  paths: PairPaths,
  en: string,
  zh: string,
  base: PairingLinkBase,
  trees: { en: Nodes; zh: Nodes },
): PairingRecord {
  // Record hashes cover the switcher paragraph too, so no switcher link is skipped during normalization.
  const normalizedEn = normalizeTranslationMarkdownLinkEdits(en, { ...base, sourcePath: paths.source }, undefined, trees.en)
  const normalizedZh = normalizeTranslationMarkdownLinkEdits(zh, { ...base, sourcePath: paths.counterpart }, undefined, trees.zh)
  const enSections = sideSections(en, normalizedEn, trees.en)
  const zhSections = sideSections(zh, normalizedZh, trees.zh)
  if (enSections.length !== zhSections.length) {
    throw new Error(`${paths.source} has ${enSections.length - 1} heading(s) but ${paths.counterpart} has ${zhSections.length - 1}`)
  }
  const record = new Map<string, SectionHashes>()
  const ancestors: { depth: number; slug: string }[] = []
  const keys = new Set<string>()
  for (const [index, enSection] of enSections.entries()) {
    const zhSection = zhSections[index]
    if (zhSection === undefined) throw new Error('section alignment lost its counterpart')
    let path = '/'
    if (enSection.heading !== undefined) {
      const depth = enSection.heading.depth
      while ((ancestors.at(-1)?.depth ?? 0) >= depth) ancestors.pop()
      ancestors.push({ depth, slug: slug(headingText(enSection.heading)) })
      path = `/${ancestors.map(ancestor => ancestor.slug).join('/')}`
    }
    let key = path
    for (let repeat = 2; keys.has(key); repeat++) key = `${path}~${repeat}`
    keys.add(key)
    if (enSection.blocks.length === 0 && zhSection.blocks.length === 0) continue
    record.set(key, { en: sectionHash(enSection.blocks), zh: sectionHash(zhSection.blocks) })
  }
  return record
}

/** Parse a consistency record; undefined when malformed or when a key repeats. */
export function parsePairingRecord(content: string): PairingRecord | undefined {
  const record = new Map<string, SectionHashes>()
  const lines = content.split('\n').filter(line => line !== '' && !line.startsWith('#'))
  for (let index = 0; index < lines.length; index += 3) {
    const key = KEY_LINE.exec(lines[index] ?? '')?.[1]
    const en = HASH_LINE.exec(lines[index + 1] ?? '')
    const zh = HASH_LINE.exec(lines[index + 2] ?? '')
    if (key === undefined || record.has(key) || en?.[1] !== 'en' || zh?.[1] !== 'zh' || !en[2] || !zh[2]) {
      return undefined
    }
    record.set(key, { en: en[2], zh: zh[2] })
  }
  return record
}

/**
 * Canonical YAML text of a record, with exactly one trailing newline. The re-record command names
 * the source below its `translation.roots` prefix, the path it has once the tree lands in a project.
 */
export function renderPairingRecord(paths: PairPaths, record: PairingRecord, roots: readonly string[] = []): string {
  const root = roots.find(prefix => paths.source.startsWith(prefix))
  const source = root === undefined ? paths.source : paths.source.slice(root.length)
  return [
    `# Bilingual-pair consistency record for ${basename(paths.source)} (scripts/tianshu translation-pairing gate): per heading`,
    '# section, a hash of its English and Chinese blocks outside code blocks and generated regions.',
    '# After editing either side, bring the other along and re-record with:',
    `#   npm --prefix scripts/tianshu run gate -- translation-pairing --write ${source}`,
    ...[...record].flatMap(([key, hashes]) => [`${key}:`, `  en: ${hashes.en}`, `  zh: ${hashes.zh}`]),
    '',
  ].join('\n')
}

/** One message per section that changed, appeared, or disappeared since confirmation. */
export function pairingRecordDiff(recorded: PairingRecord, current: PairingRecord): string[] {
  const out: string[] = []
  for (const [key, hashes] of current) {
    const confirmed = recorded.get(key)
    if (confirmed === undefined) {
      out.push(`section ${key} has unconfirmed translated content`)
      continue
    }
    const sides = (['en', 'zh'] as const).filter(side => confirmed[side] !== hashes[side])
    if (sides.length > 0) out.push(`section ${key} changed since confirmation (${sides.join(', ')})`)
  }
  for (const key of recorded.keys()) {
    if (!current.has(key)) out.push(`section ${key} is recorded but no longer has translated content`)
  }
  return out
}

/** Structural signature compared between the two sides of a pair. */
export interface StructureSignature {
  headings: number[]
  code: string[]
  tables: string[]
  lists: string[]
  links: string[]
}

/** Ordered structure of one side; the language switcher is excluded from links. */
export function structureSignature(
  tree: Nodes,
  markdown: string,
  switcher: SwitcherSpec,
  linkContext: TranslationLinkContext,
): StructureSignature {
  const switcherOffset = languageSwitcherLinkOffset(tree, markdown, switcher)
  const sig: StructureSignature = { headings: [], code: [], tables: [], lists: [], links: [] }
  const definitions = new Map<string, Extract<Nodes, { type: 'definition' }>>()
  const collectDefinitions = (node: Nodes): void => {
    if (node.type === 'definition' && !definitions.has(node.identifier)) definitions.set(node.identifier, node)
    if ('children' in node) for (const child of node.children) collectDefinitions(child)
  }
  collectDefinitions(tree)
  const linkTarget = (node: LinkNode): string => semanticTranslationLinkNodeTarget(node, markdown, linkContext)
  const visit = (node: Nodes): void => {
    switch (node.type) {
      case 'heading':
        sig.headings.push(node.depth)
        break
      case 'code':
        sig.code.push(`\`\`\`${node.lang ?? ''}${node.meta ? ` ${node.meta}` : ''}\n${node.value}`)
        break
      case 'table':
        sig.tables.push(`${node.children.length}x${node.children[0]?.children.length ?? 0}`)
        break
      case 'list':
        sig.lists.push(node.ordered
          ? `ordered:start=${node.start ?? 1}:items=${node.children.length}`
          : `bullet:items=${node.children.length}`)
        break
      case 'link':
        if (node.position?.start.offset !== switcherOffset) sig.links.push(linkTarget(node))
        break
      case 'linkReference': {
        const definition = definitions.get(node.identifier)
        if (definition !== undefined) sig.links.push(linkTarget(definition))
        break
      }
      default:
        break
    }
    if ('children' in node) for (const child of node.children) visit(child)
  }
  visit(tree)
  return sig
}

function show(value: string | number | undefined): string {
  if (value === undefined) return 'nothing'
  const text = JSON.stringify(value)
  return text.length > 72 ? `${text.slice(0, 72)}…` : text
}

/** First divergence per structural field; empty when the two signatures agree. */
export function structureDiff(source: StructureSignature, counterpart: StructureSignature): string[] {
  const out: string[] = []
  const fields: [string, (string | number)[], (string | number)[]][] = [
    ['heading (depth)', source.headings, counterpart.headings],
    ['code block', source.code, counterpart.code],
    ['table (row x column count)', source.tables, counterpart.tables],
    ['list (kind, start, item count)', source.lists, counterpart.lists],
    ['link target', source.links, counterpart.links],
  ]
  for (const [field, sourceValues, counterpartValues] of fields) {
    const length = Math.max(sourceValues.length, counterpartValues.length)
    for (let index = 0; index < length; index++) {
      if (sourceValues[index] !== counterpartValues[index]) {
        out.push(`${field} #${index + 1} diverges between the pair: ${show(sourceValues[index])} vs ${show(counterpartValues[index])}`)
        break
      }
    }
  }
  return out
}
