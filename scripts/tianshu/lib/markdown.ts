/** Adapted from deepseek-ai/deepseek-harness (MIT), scripts/markdown.ts. Subset: parsing, traversal, destinations, headings. */

import { fromMarkdown } from 'mdast-util-from-markdown'
import { gfmFromMarkdown } from 'mdast-util-gfm'
import { gfm } from 'micromark-extension-gfm'
import type { Nodes } from 'mdast'

/** One parsed Markdown heading, retaining its source line and rendered text. */
export interface MarkdownHeadingLine {
  depth: number
  /** 1-based source line. */
  index: number
  /** Rendered heading text, excluding raw HTML such as comments. */
  text: string
}

/** Markdown nodes whose authored destination occupies a replaceable source range. */
export type MarkdownDestinationNode = Extract<Nodes, { type: 'link' | 'image' | 'definition' }>

/** One authored Markdown destination and its absolute source offsets. */
export interface MarkdownDestination {
  start: number
  end: number
  url: string
}

/** Parse GitHub-flavored Markdown with the standard extensions. */
export function parseMarkdown(source: string): Nodes {
  return fromMarkdown(source, { extensions: [gfm()], mdastExtensions: [gfmFromMarkdown()] })
}

/** Visit a Markdown tree depth-first; returning false prunes a node's children. */
export function visitMarkdown(node: Nodes, visitor: (node: Nodes) => boolean | void): void {
  if (visitor(node) === false) return
  if ('children' in node) {
    for (const child of node.children) visitMarkdown(child, visitor)
  }
}

/** Whether a Markdown URL is external, repository-root absolute, or purely in-page. */
export function isExternalOrAbsoluteMarkdownUrl(url: string): boolean {
  return url.startsWith('#')
    || url.startsWith('//')
    || url.startsWith('/')
    || /^[a-zA-Z][a-zA-Z0-9+.-]*:/.test(url)
}

/** Split one Markdown URL without normalizing its query or fragment suffix. */
export function splitMarkdownUrlTarget(url: string): { path: string; suffix: string } {
  const boundary = url.search(/[?#]/)
  if (boundary === -1) return { path: url, suffix: '' }
  return { path: url.slice(0, boundary), suffix: url.slice(boundary) }
}

function skipWhitespace(source: string, start: number): number {
  let index = start
  while (/\s/.test(source[index] ?? '')) index += 1
  return index
}

function labelEnd(source: string): number {
  const first = source.indexOf('[')
  if (first === -1) return -1
  let depth = 0
  for (let index = first; index < source.length; index += 1) {
    const char = source[index]
    if (char === '\\') index += 1
    else if (char === '[') depth += 1
    else if (char === ']') {
      depth -= 1
      if (depth === 0) return index
    }
  }
  return -1
}

function destinationRange(rawNode: string, type: MarkdownDestinationNode['type']): { start: number; end: number } {
  const endOfLabel = labelEnd(rawNode)
  if (endOfLabel === -1) throw new Error(`markdown: cannot locate label end in ${JSON.stringify(rawNode)}`)
  let start: number
  if (type === 'definition') {
    const colon = rawNode.indexOf(':', endOfLabel + 1)
    if (colon === -1) throw new Error(`markdown: cannot locate definition separator in ${JSON.stringify(rawNode)}`)
    start = skipWhitespace(rawNode, colon + 1)
  } else {
    if (rawNode[endOfLabel + 1] !== '(') {
      throw new Error(`markdown: cannot locate inline destination in ${JSON.stringify(rawNode)}`)
    }
    start = skipWhitespace(rawNode, endOfLabel + 2)
  }
  if (rawNode[start] === '<') {
    for (let index = start + 1; index < rawNode.length; index += 1) {
      if (rawNode[index] === '\\') index += 1
      else if (rawNode[index] === '>') return { start: start + 1, end: index }
    }
    throw new Error(`markdown: cannot locate angle-bracket destination end in ${JSON.stringify(rawNode)}`)
  }
  let depth = 0
  for (let index = start; index < rawNode.length; index += 1) {
    const char = rawNode[index]
    if (char === '\\') index += 1
    else if (char === '(') depth += 1
    else if (char === ')') {
      if (depth === 0) return { start, end: index }
      depth -= 1
    } else if (/\s/.test(char ?? '') && depth === 0) {
      return { start, end: index }
    }
  }
  return { start, end: rawNode.length }
}

/** Locate one parsed destination in the original Markdown without reserializing it. */
export function markdownDestination(source: string, node: MarkdownDestinationNode): MarkdownDestination {
  const start = node.position?.start.offset
  const end = node.position?.end.offset
  if (start === undefined || end === undefined) {
    throw new Error(`markdown: destination ${JSON.stringify(node.url)} has no source offsets`)
  }
  const range = destinationRange(source.slice(start, end), node.type)
  const absolute = { start: start + range.start, end: start + range.end }
  return { ...absolute, url: source.slice(absolute.start, absolute.end) }
}

/** Text a reader sees from one Markdown node; raw HTML contributes none. */
function renderedText(node: Nodes): string {
  if (node.type === 'text' || node.type === 'inlineCode') return node.value
  if (node.type === 'image' || node.type === 'imageReference') return node.alt ?? ''
  if (node.type === 'break') return ' '
  if ('children' in node) return node.children.map(child => renderedText(child)).join('')
  return ''
}

/** Every parsed heading with its rendered text and source line, in document order. */
export function markdownHeadingLines(source: string, tree: Nodes = parseMarkdown(source)): MarkdownHeadingLine[] {
  const headings: MarkdownHeadingLine[] = []
  visitMarkdown(tree, (node) => {
    if (node.type !== 'heading' || node.position === undefined) return
    headings.push({ depth: node.depth, index: node.position.start.line, text: renderedText(node) })
  })
  return headings
}
