/** Adapted from deepseek-ai/deepseek-harness (MIT), scripts/verify-md-links.ts. Scope is the repository's Markdown; symlink dedupe dropped. */

import { posix } from 'node:path'
import type { Nodes } from 'mdast'
import { markdownHeadingLines, parseMarkdown, visitMarkdown } from '../lib/markdown.ts'
import { violation, type Ctx, type Gate, type Violation } from '../lib/context.ts'

/** Archived Agent Notes are frozen: not checked as sources, but links into them still resolve. */
const ARCHIVE_EXCLUDE = ['.agents/notes/archived/**']

interface LinkDocument {
  destinations: { url: string; line: number }[]
  anchors: Set<string>
}

/**
 * True for targets this gate does not judge: scheme URLs, protocol-relative, and root-absolute.
 * Pure in-page anchors (`#frag`) are checked against the source file itself.
 */
function isExternal(url: string): boolean {
  if (url.startsWith('//') || url.startsWith('/')) return true
  return /^[a-zA-Z][a-zA-Z0-9+.-]*:/.test(url)
}

/** Strip `#fragment` and `?query`, then percent-decode; a malformed escape keeps the raw path so it reports broken. */
function pathPart(url: string): string {
  const raw = url.replace(/[#?].*$/, '')
  try {
    return decodeURIComponent(raw)
  } catch {
    return raw
  }
}

/** Percent-decoded `#fragment`, or null when the link has none. */
function fragmentPart(url: string): string | null {
  const hash = url.indexOf('#')
  if (hash === -1) return null
  const raw = url.slice(hash + 1).replace(/\?.*$/, '')
  try {
    return decodeURIComponent(raw)
  } catch {
    return raw
  }
}

/** GitHub heading slug: lowercase, drop everything but letters, digits, `_`, spaces, hyphens; spaces become hyphens. */
export function githubSlug(heading: string): string {
  return heading.toLowerCase().replace(/[^\p{L}\p{N}_ -]/gu, '').replaceAll(' ', '-')
}

/**
 * Every anchor a document exposes: each heading's GitHub slug (with GitHub's `-1`, `-2`
 * suffixes for repeats) plus explicit `<a id="...">` in real HTML flow.
 */
export function documentAnchors(source: string, tree: Nodes = parseMarkdown(source)): Set<string> {
  const anchors = new Set<string>()
  const occurrences = new Map<string, number>()
  for (const heading of markdownHeadingLines(source, tree)) {
    const base = githubSlug(heading.text)
    let result = base
    let bump = occurrences.get(base) ?? 0
    while (anchors.has(result)) {
      bump += 1
      result = `${base}-${bump}`
    }
    occurrences.set(base, bump)
    anchors.add(result)
  }
  visitMarkdown(tree, (node: Nodes): void => {
    if (node.type !== 'html') return
    const html = node.value.replace(/<!--[\s\S]*?-->/g, '')
    for (const match of html.matchAll(/<a id="([^"]+)"/g)) anchors.add(match[1] ?? '')
  })
  return anchors
}

function linkDocument(source: string): LinkDocument {
  const tree = parseMarkdown(source)
  const destinations: LinkDocument['destinations'] = []
  visitMarkdown(tree, (node: Nodes): void => {
    if ((node.type === 'link' || node.type === 'image' || node.type === 'definition') && 'url' in node) {
      destinations.push({ url: node.url, line: node.position?.start.line ?? 0 })
    }
  })
  return { destinations, anchors: documentAnchors(source, tree) }
}

/** Find every broken relative link or fragment in one Markdown file. */
function findBrokenLinks(ctx: Ctx, rel: string, documents: Map<string, LinkDocument>): Violation[] {
  const document = (path: string): LinkDocument => {
    const hit = documents.get(path)
    if (hit !== undefined) return hit
    const parsed = linkDocument(ctx.text(path) ?? '')
    documents.set(path, parsed)
    return parsed
  }
  const out: Violation[] = []
  for (const { url, line } of document(rel).destinations) {
    if (isExternal(url)) continue
    const target = pathPart(url).replace(/\/+$/, '')
    const resolved = target === '' ? rel : posix.normalize(posix.join(posix.dirname(rel), target))
    if (resolved.startsWith('../') || !ctx.exists(resolved)) {
      out.push(violation(rel, line, 'md-links', `${url}: target does not exist`))
      continue
    }
    const fragment = fragmentPart(url)
    if (fragment === null || !resolved.endsWith('.md')) continue
    if (!document(resolved).anchors.has(fragment)) {
      out.push(violation(rel, line, 'md-links', `${url}: no such anchor in target`))
    }
  }
  return out
}

export const mdLinks: Gate = {
  name: 'md-links',
  summary: 'relative Markdown links, images, and fragments resolve',
  runAll: true,
  run(ctx) {
    const documents = new Map<string, LinkDocument>()
    return ctx.list(['**/*.md'], ARCHIVE_EXCLUDE)
      .filter(file => ctx.inScope(file))
      .flatMap(file => findBrokenLinks(ctx, file, documents))
  },
}
