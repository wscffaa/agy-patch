import type { Gate } from '../lib/context.ts'
import { agentNoteFormat } from './agent-note-format.ts'
import { archivedAgentNotes } from './archived-agent-notes.ts'
import { docBudgets } from './doc-budgets.ts'
import { issuePolicy } from './issue-policy.ts'
import { mdLinks } from './md-links.ts'
import { mdWrap } from './md-wrap.ts'
import { repositoryReferences } from './repository-references.ts'
import { translationPairing } from './translation-pairing.ts'

/** Every gate, in the order `gates` runs them. */
export const GATES: Gate[] = [
  agentNoteFormat,
  archivedAgentNotes,
  docBudgets,
  mdLinks,
  mdWrap,
  translationPairing,
  repositoryReferences,
  issuePolicy,
]
