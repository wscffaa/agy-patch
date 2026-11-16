/** Adapted from deepseek-ai/deepseek-harness (MIT), scripts/translation-links.ts. Repository access is injected instead of read from disk. */

import { posix } from 'node:path'
import type { Nodes } from 'mdast'
import {
  isExternalOrAbsoluteMarkdownUrl,
  markdownDestination,
  parseMarkdown,
  splitMarkdownUrlTarget,
  visitMarkdown,
  type MarkdownDestination,
} from './markdown.ts'

/** Repository and source document used to resolve one relative link. */
export interface TranslationLinkContext {
  /** Repository-relative Markdown source path. */
  sourcePath: string
  /** Counterpart suffix including `.md`, e.g. `.zh.md`. */
  counterpartSuffix: string
  /** Whether an English source path belongs to the bilingual corpus. */
  isPairSource: (sourcePath: string) => boolean
  /** Existence probe in the selected content plane. */
  exists: (repoPath: string) => boolean
  /** `translation.roots` prefixes; a link target under the source's root is identified by its path below that root. */
  roots?: readonly string[]
}

/** Accepted language-switcher destinations and the regex that matches the switcher paragraph. */
export interface SwitcherSpec {
  accepted: readonly string[]
  pattern: RegExp
}

/** One relative document link whose target uses the wrong locale sibling. */
export interface TranslationLinkLocaleViolation {
  sourcePath: string
  line: number
  url: string
  expectedUrl: string
}

interface TranslationPairTarget {
  source: string
  counterpart: string
}

interface ResolvedTranslationLink {
  pair: TranslationPairTarget
  targetPath: string
  suffix: string
  expectedPath: string
  expectedUrl: string
  locale: 'source' | 'counterpart'
}

interface Replacement {
  start: number
  end: number
  value: string
}

/** Markdown nodes whose destinations translation links resolve. */
export type LinkNode = Extract<Nodes, { type: 'link' | 'definition' }>

/** One authored destination that link normalization replaced. */
export interface TranslationLinkDestinationEdit {
  node: LinkNode
  start: number
  end: number
  /** Semantic target text that replaces `markdown.slice(start, end)`. */
  value: string
}

/** Normalized Markdown text and the destination edits that produced it. */
export interface TranslationLinkNormalization {
  content: string
  edits: TranslationLinkDestinationEdit[]
}

/** Offset of the one top-level switcher link immediately following the H1. */
export function languageSwitcherLinkOffset(tree: Nodes, markdown: string, switcher: SwitcherSpec | undefined): number | undefined {
  if (tree.type !== 'root' || switcher === undefined) return undefined
  const accepted = new Set(switcher.accepted)
  const headingIndex = tree.children.findIndex(node => node.type === 'heading' && node.depth === 1)
  if (headingIndex < 0) return undefined
  for (const node of tree.children.slice(headingIndex + 1)) {
    if (node.type === 'heading') return undefined
    if (node.type !== 'paragraph' || node.position === undefined) continue
    const start = node.position.start.offset
    const end = node.position.end.offset
    if (start === undefined || end === undefined) continue
    if (!switcher.pattern.test(markdown.slice(start, end))) continue
    const links = node.children.filter((child): child is Extract<Nodes, { type: 'link' }> => child.type === 'link')
    if (links.length === 1 && accepted.has(links[0]?.url ?? '')) {
      return links[0]?.position?.start.offset
    }
  }
  return undefined
}

/** Whether the tree carries its canonical top-level language switcher. */
export function hasLanguageSwitcher(tree: Nodes, markdown: string, switcher: SwitcherSpec): boolean {
  return languageSwitcherLinkOffset(tree, markdown, switcher) !== undefined
}

function decodePath(path: string): string {
  try {
    return decodeURIComponent(path)
  } catch {
    return path
  }
}

function repositoryRelativePath(path: string): string | undefined {
  const normalized = posix.normalize(path)
  if (normalized === '' || normalized === '.' || normalized === '..' || normalized.startsWith('../') || posix.isAbsolute(normalized)) {
    return undefined
  }
  return normalized
}

function resolveRepositoryTarget(rawPath: string, context: TranslationLinkContext): string | undefined {
  const exact = repositoryRelativePath(posix.join(posix.dirname(context.sourcePath), decodePath(rawPath)))
  if (exact === undefined) return undefined
  return context.exists(exact) ? exact : undefined
}

function translationPairTarget(targetPath: string, context: TranslationLinkContext): TranslationPairTarget | undefined {
  const suffix = context.counterpartSuffix
  const source = targetPath.endsWith(suffix)
    ? `${targetPath.slice(0, -suffix.length)}.md`
    : targetPath.endsWith('.md') ? targetPath : undefined
  if (source === undefined || !context.isPairSource(source)) return undefined
  return { source, counterpart: `${source.slice(0, -3)}${suffix}` }
}

/**
 * Repository path of a paired target as recorded in hashes: below the source document's
 * `translation.roots` prefix when both sit under it, so a vendored tree records the same
 * identities it has once copied to a project root.
 * Note: .agents/notes/implemented/process/2026-10-31-kit-init-lands-clean.md
 */
function recordedTargetPath(targetSource: string, context: TranslationLinkContext): string {
  const root = context.roots?.find(prefix => context.sourcePath.startsWith(prefix))
  return root !== undefined && targetSource.startsWith(root) ? targetSource.slice(root.length) : targetSource
}

function encodePathSegment(segment: string): string {
  return encodeURIComponent(segment).replace(/[!'()*]/g, character => (
    `%${character.charCodeAt(0).toString(16).toUpperCase()}`
  ))
}

function relativeExpectedPath(context: TranslationLinkContext, expectedPath: string, rawPath: string): string {
  const relative = posix.relative(posix.dirname(context.sourcePath), expectedPath)
  const encoded = relative.split('/').map(encodePathSegment).join('/')
  return rawPath.startsWith('./') && !encoded.startsWith('.') ? `./${encoded}` : encoded
}

function expectedLocalePath(rawPath: string, locale: 'source' | 'counterpart', context: TranslationLinkContext, expectedPath: string): string {
  const suffix = context.counterpartSuffix
  if (locale === 'counterpart' && rawPath.endsWith('.md') && !rawPath.endsWith(suffix)) {
    return `${rawPath.slice(0, -3)}${suffix}`
  }
  if (locale === 'source' && rawPath.endsWith(suffix)) return `${rawPath.slice(0, -suffix.length)}.md`
  return relativeExpectedPath(context, expectedPath, rawPath)
}

function resolveTranslationLink(url: string, context: TranslationLinkContext, authoredUrl: string): ResolvedTranslationLink | undefined {
  if (isExternalOrAbsoluteMarkdownUrl(url)) return undefined
  const { path } = splitMarkdownUrlTarget(url)
  const authored = splitMarkdownUrlTarget(authoredUrl)
  if (path === '') return undefined
  const targetPath = resolveRepositoryTarget(path, context)
  if (targetPath === undefined) return undefined
  const pair = translationPairTarget(targetPath, context)
  if (pair === undefined) return undefined
  const locale = context.sourcePath.endsWith(context.counterpartSuffix) ? 'counterpart' : 'source'
  const expectedPath = locale === 'counterpart' ? pair.counterpart : pair.source
  return {
    pair,
    targetPath,
    suffix: authored.suffix,
    expectedPath,
    expectedUrl: `${expectedLocalePath(authored.path, locale, context, expectedPath)}${authored.suffix}`,
    locale,
  }
}

function authoredExternalTarget(markdown: string, node: LinkNode): string {
  const start = node.position?.start.offset
  const end = node.position?.end.offset
  if (start === undefined || end === undefined) {
    throw new Error(`translation-links: external link ${JSON.stringify(node.url)} has no source offsets`)
  }
  const raw = markdown.slice(start, end)
  if (node.type === 'definition' || raw.startsWith('[')) return markdownDestination(markdown, node).url
  if (raw.startsWith('<') && raw.endsWith('>')) return raw.slice(1, -1)
  return raw
}

function applyReplacements(markdown: string, replacements: Replacement[]): string {
  let output = markdown
  for (const replacement of [...replacements].sort((left, right) => right.start - left.start)) {
    output = output.slice(0, replacement.start) + replacement.value + output.slice(replacement.end)
  }
  return output
}

function visitDocumentLinkNodes(markdown: string, switcher: SwitcherSpec | undefined, visitor: (node: LinkNode) => void, tree: Nodes): void {
  const switcherOffset = languageSwitcherLinkOffset(tree, markdown, switcher)
  const referencedIdentifiers = new Set<string>()
  const visitedDefinitions = new Set<string>()
  visitMarkdown(tree, (node) => {
    if (node.type === 'linkReference') referencedIdentifiers.add(node.identifier)
  })
  visitMarkdown(tree, (node) => {
    if (node.type === 'link' && node.position?.start.offset === switcherOffset) return
    if (node.type === 'link') {
      visitor(node)
    } else if (node.type === 'definition'
      && referencedIdentifiers.has(node.identifier)
      && !visitedDefinitions.has(node.identifier)) {
      visitedDefinitions.add(node.identifier)
      visitor(node)
    }
  })
}

function visitResolvedDocumentLinks(
  markdown: string,
  context: TranslationLinkContext,
  switcher: SwitcherSpec | undefined,
  visitor: (node: LinkNode, destination: MarkdownDestination, resolved: ResolvedTranslationLink) => void,
  tree: Nodes,
): void {
  visitDocumentLinkNodes(markdown, switcher, (node) => {
    if (isExternalOrAbsoluteMarkdownUrl(node.url)) return
    const destination = markdownDestination(markdown, node)
    const resolved = resolveTranslationLink(node.url, context, destination.url)
    if (resolved !== undefined) visitor(node, destination, resolved)
  }, tree)
}

/** One violation per wrong-locale link or link definition, in document order. */
export function translationLinkLocaleViolations(
  markdown: string,
  context: TranslationLinkContext,
  switcher: SwitcherSpec | undefined,
  tree: Nodes = parseMarkdown(markdown),
): TranslationLinkLocaleViolation[] {
  const violations: TranslationLinkLocaleViolation[] = []
  visitResolvedDocumentLinks(markdown, context, switcher, (node, destination, resolved) => {
    if (resolved.targetPath === resolved.expectedPath) return
    violations.push({
      sourcePath: context.sourcePath,
      line: node.position?.start.line ?? 0,
      url: destination.url,
      expectedUrl: resolved.expectedUrl,
    })
  }, tree)
  return violations
}

/**
 * Replace paired-document destinations with one semantic target each, keeping every other byte.
 * Returns the normalized text and the destination edits in ascending source order.
 */
export function normalizeTranslationMarkdownLinkEdits(
  markdown: string,
  context: TranslationLinkContext,
  switcher: SwitcherSpec | undefined,
  tree: Nodes = parseMarkdown(markdown),
): TranslationLinkNormalization {
  const edits: TranslationLinkDestinationEdit[] = []
  visitResolvedDocumentLinks(markdown, context, switcher, (node, destination, resolved) => {
    edits.push({
      node,
      start: destination.start,
      end: destination.end,
      value: `tianshu-translation-target:${recordedTargetPath(resolved.pair.source, context)}${resolved.suffix}`,
    })
  }, tree)
  const content = applyReplacements(markdown, edits.map(edit => ({ start: edit.start, end: edit.end, value: edit.value })))
  return { content, edits: edits.sort((left, right) => left.start - right.start) }
}

/** Semantic target of one authored inline link or referenced definition. */
export function semanticTranslationLinkNodeTarget(node: LinkNode, markdown: string, context: TranslationLinkContext): string {
  if (isExternalOrAbsoluteMarkdownUrl(node.url)) return authoredExternalTarget(markdown, node)
  const destination = markdownDestination(markdown, node)
  const resolved = resolveTranslationLink(node.url, context, destination.url)
  return resolved === undefined
    ? destination.url
    : `tianshu-translation-target:${recordedTargetPath(resolved.pair.source, context)}${resolved.suffix}`
}
