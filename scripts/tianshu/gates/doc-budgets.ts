/** Adapted from deepseek-ai/deepseek-harness (MIT), scripts/verify-doc-budgets.ts. Manifest moved to .tianshu/. */

import { violation, type Gate, type Violation } from '../lib/context.ts'

export const DOC_BUDGETS = '.tianshu/doc-budgets.json'

/** `wc -w` equivalent: count whitespace-delimited tokens. */
function countWords(text: string): number {
  return text.split(/\s+/).filter(Boolean).length
}

export const docBudgets: Gate = {
  name: 'doc-budgets',
  summary: 'word ceilings for budgeted standing docs',
  runAll: true,
  run(ctx) {
    const manifestText = ctx.text(DOC_BUDGETS)
    if (manifestText === undefined) {
      ctx.notice(`${DOC_BUDGETS} not found; doc budgets not enforced`)
      return []
    }
    const out: Violation[] = []
    let manifest: Record<string, unknown>
    try {
      manifest = JSON.parse(manifestText) as Record<string, unknown>
    } catch (error) {
      return [violation(DOC_BUDGETS, 0, 'doc-budget', `invalid JSON (${error instanceof Error ? error.message : String(error)})`)]
    }
    for (const [path, ceiling] of Object.entries(manifest)) {
      if (!Number.isInteger(ceiling) || (ceiling as number) <= 0) {
        out.push(violation(DOC_BUDGETS, 0, 'doc-budget', `${path}: ceiling must be a positive integer, got ${String(ceiling)}`))
        continue
      }
      if (!ctx.exists(path)) {
        out.push(violation(DOC_BUDGETS, 0, 'doc-budget', `${path}: budgeted file does not exist (renamed or deleted? update ${DOC_BUDGETS})`))
        continue
      }
      const words = countWords(ctx.text(path) ?? '')
      if (words > (ceiling as number) && ctx.inScope(path)) {
        out.push(violation(path, 0, 'doc-budget', `${words} words exceeds the ${String(ceiling)}-word ceiling; condense or relocate, or raise the ceiling with justification`))
      }
    }
    return out
  },
}
