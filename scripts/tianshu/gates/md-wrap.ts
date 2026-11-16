/** Adapted from deepseek-ai/deepseek-harness (MIT), scripts/verify-md-wrap.ts. VitePress container masking dropped. */

import type { Nodes } from 'mdast'
import { parseMarkdown, visitMarkdown } from '../lib/markdown.ts'
import { violation, type Ctx, type Gate, type Violation } from '../lib/context.ts'

const ARCHIVE_EXCLUDE = ['.agents/notes/archived/**']

/** Blank the YAML frontmatter block so its delimiters do not parse as thematic breaks. Line numbers are preserved. */
function maskFrontmatter(source: string): string {
  const lines = source.split('\n')
  if (lines[0] === '---') {
    const closing = lines.indexOf('---', 1)
    if (closing !== -1) {
      for (let index = 0; index <= closing; index++) lines[index] = ''
    }
  }
  return lines.join('\n')
}

/** Every prose paragraph that spans more than one physical source line. */
function findHardWraps(rel: string, source: string): Violation[] {
  const lines = source.split('\n')
  const out: Violation[] = []
  visitMarkdown(parseMarkdown(maskFrontmatter(source)), (node: Nodes): boolean | void => {
    if (node.type === 'paragraph' && node.position) {
      const { start, end } = node.position
      if (end.line > start.line) {
        const text = (lines[start.line - 1] ?? '').trim()
        const shown = text.length > 80 ? `${text.slice(0, 80)}…` : text
        out.push(violation(rel, start.line, 'md-wrap', `hard-wrapped paragraph; write one physical line per paragraph: ${shown}`))
      }
      // Paragraph children are inline, so no nested paragraph needs a visit.
      return false
    }
  })
  return out
}

export const mdWrap: Gate = {
  name: 'md-wrap',
  summary: 'prose paragraphs are one physical line each',
  runAll: true,
  run(ctx: Ctx) {
    return ctx.list(['**/*.md'], ARCHIVE_EXCLUDE)
      .filter(file => ctx.inScope(file))
      .flatMap(file => findHardWraps(file, ctx.text(file) ?? ''))
  },
}
