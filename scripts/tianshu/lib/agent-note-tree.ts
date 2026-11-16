/** Adapted from deepseek-ai/deepseek-harness (MIT), scripts/agent-note-tree.ts. */

import { violation, type Ctx, type Violation } from './context.ts'

/** Root of the Agent Note tree, relative to the repository. */
export const AGENT_NOTE_ROOT = '.agents/notes'

/** The closed set of Agent Note classes (nested folder under each lifecycle). Extend it deliberately. */
export const AGENT_NOTE_CLASSES = ['feature', 'bug-fix', 'simplification', 'architecture', 'process', 'testing'] as const

/** Active lifecycles; `archived/` is handled by the archived-agent-notes gate. */
export const AGENT_NOTE_LIFECYCLES = ['proposed', 'implemented', 'rejected'] as const

const ARCHIVE_DIR = 'archived'

/** Non-note Markdown allowed directly under a lifecycle folder. */
const ROOT_ALLOWLIST = new Set(['AGENTS.md', 'CLAUDE.md'])

/** One active Agent Note discovered by the tree walk. */
export interface AgentNote {
  lifecycle: string
  /** Repository-relative path. */
  path: string
  /** `yyyy-mm-dd` from the filename. */
  date: string
}

/**
 * Walk the Agent Note tree and enforce its structure: closed lifecycle and class
 * folders, `{lifecycle}/{class}/yyyy-mm-dd-topic.md` depth, and no centralized INDEX.md.
 * Chinese counterparts (`.zh.md`) are indexed via their English file.
 */
export function walkAgentNoteTree(ctx: Ctx): { notes: AgentNote[]; errors: Violation[] } {
  const notes: AgentNote[] = []
  const errors: Violation[] = []
  const prefix = `${AGENT_NOTE_ROOT}/`
  for (const file of ctx.list([`${AGENT_NOTE_ROOT}/**/*`])) {
    const rel = file.slice(prefix.length)
    const segs = rel.split('/')
    if (segs.length === 1) {
      if (rel === 'INDEX.md') {
        errors.push(violation(file, 0, 'structure', 'centralized Agent Note indexes are forbidden; browse the lifecycle/class tree or search the repository'))
      }
      continue
    }
    const top = segs[0] ?? ''
    if (top === ARCHIVE_DIR || !file.endsWith('.md')) continue
    if (!(AGENT_NOTE_LIFECYCLES as readonly string[]).includes(top)) {
      errors.push(violation(file, 0, 'structure', `unknown lifecycle folder "${top}" (allowed: ${AGENT_NOTE_LIFECYCLES.join(', ')}, plus ${ARCHIVE_DIR}/)`))
      continue
    }
    if (segs.length === 2 && ROOT_ALLOWLIST.has(segs[1] ?? '')) continue
    if (file.endsWith('.zh.md')) continue
    if (segs.length !== 3) {
      errors.push(violation(file, 0, 'structure', `expected ${AGENT_NOTE_ROOT}/{lifecycle}/{class}/file.md (got depth ${segs.length})`))
      continue
    }
    const cls = segs[1] ?? ''
    const base = segs[2] ?? ''
    if (!(AGENT_NOTE_CLASSES as readonly string[]).includes(cls)) {
      errors.push(violation(file, 0, 'structure', `unknown class folder "${cls}" (allowed: ${AGENT_NOTE_CLASSES.join(', ')})`))
      continue
    }
    if (!/^\d{4}-\d{2}-\d{2}-.+\.md$/.test(base)) {
      errors.push(violation(file, 0, 'structure', 'filename must be yyyy-mm-dd-topic.md'))
      continue
    }
    notes.push({ lifecycle: top, path: file, date: base.slice(0, 10) })
  }
  return { notes, errors }
}
