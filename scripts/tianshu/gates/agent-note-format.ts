/** Adapted from deepseek-ai/deepseek-harness (MIT), scripts/verify-agent-note-format.ts and scripts/verify-agent-note-classification.ts. */

import { walkAgentNoteTree, type AgentNote } from '../lib/agent-note-tree.ts'
import { violation, type Ctx, type Gate, type Violation } from '../lib/context.ts'

/** Exact comment a pre-format Agent Note carries in place of `## Alternatives considered`. */
const GRANDFATHER = '<!-- agent-note-format: alternatives-not-recorded (pre-format Agent Note) -->'

/** Status-line grammar per lifecycle folder. */
const STATUS: Record<string, RegExp> = {
  proposed: /^Status: proposed$/,
  implemented: /^Status: implemented$/,
  rejected: /^Status: rejected — .+$/,
}

/** Required `##` headings per lifecycle, beyond the universal `## Problem` opener. */
const REQUIRED: Record<string, string[]> = {
  proposed: ['## Proposal', '## Acceptance criteria', '## Risks'],
  implemented: ['## Decision', '## Consequences'],
  rejected: ['## Proposal'],
}

/** Proposal-era headings banned in `implemented/`. */
const BANNED_IMPLEMENTED = /^## (?:Proposal\b|Plan\b|Migration plan\b|Acceptance criteria\b)/i

/** Lines of a note outside fenced code blocks. */
function proseLines(lines: string[]): string[] {
  let inFence = false
  return lines.filter((line) => {
    if (line.startsWith('```')) {
      inFence = !inFence
      return false
    }
    return !inFence
  })
}

function checkNote(ctx: Ctx, note: AgentNote): Violation[] {
  const out: Violation[] = []
  const fail = (message: string): void => {
    out.push(violation(note.path, 0, 'agent-note-format', message))
  }
  const lines = (ctx.text(note.path) ?? '').split('\n')
  const prose = proseLines(lines)

  if (!/^# Agent Note: \S/.test(lines[0] ?? '')) fail('line 1 must be `# Agent Note: <title>`')
  if (lines[1] !== '') fail('line 2 must be blank')
  const status = STATUS[note.lifecycle]
  if (status !== undefined && !status.test(lines[2] ?? '')) {
    fail(`line 3 must match the ${note.lifecycle} status grammar (${String(status)})`)
  }
  if (lines[3] !== '') fail('line 4 must be blank')
  const statusLines = prose.filter(l => l.startsWith('Status:') && l !== lines[2])
  if (statusLines.length > 0 || prose.filter(l => l === lines[2]).length > 1) {
    fail('the line-3 `Status:` line must be the only one in the file')
  }

  const h2s = prose.filter(l => l.startsWith('## ')).map(l => l.trimEnd())
  if (h2s[0] !== '## Problem') fail(`the first section must be \`## Problem\` (got ${JSON.stringify(h2s[0] ?? '<none>')})`)
  for (const required of REQUIRED[note.lifecycle] ?? []) {
    if (!h2s.includes(required)) fail(`missing the required \`${required}\` section`)
  }
  if (note.lifecycle === 'implemented') {
    for (const h2 of h2s.filter(h => BANNED_IMPLEMENTED.test(h))) {
      fail(`\`${h2}\` is a proposal-era heading; an implemented Agent Note states what is (fold it into Decision/Consequences/Testing)`)
    }
  }

  const hasSection = h2s.includes('## Alternatives considered')
  const hasGrandfather = prose.includes(GRANDFATHER)
  const cutoff = ctx.config.agentNotes.legacyCutoff
  if (hasSection && hasGrandfather) fail('carries both `## Alternatives considered` and the grandfather comment; drop the comment')
  if (!hasSection && !hasGrandfather) fail('missing `## Alternatives considered` (an unreconstructible pre-format note may carry the grandfather comment instead; see .agents/notes/README.md)')
  if (hasGrandfather && (cutoff === null || note.date >= cutoff)) {
    fail(cutoff === null
      ? 'the grandfather comment needs `agentNotes.legacyCutoff` in .tianshu/config.json'
      : `the grandfather comment is only valid for Agent Notes dated before ${cutoff}`)
  }
  return out
}

export const agentNoteFormat: Gate = {
  name: 'agent-note-format',
  summary: 'Agent Note tree layout, header block, lifecycle sections, alternatives',
  runAll: true,
  run(ctx) {
    if (!ctx.exists('.agents/notes')) {
      ctx.notice('.agents/notes not found; agent-note-format skipped')
      return []
    }
    const { notes, errors } = walkAgentNoteTree(ctx)
    const out = errors.filter(error => ctx.inScope(error.file))
    for (const note of notes) {
      if (ctx.inScope(note.path)) out.push(...checkNote(ctx, note))
    }
    return out
  },
}
