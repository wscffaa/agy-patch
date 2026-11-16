/**
 * Tianshu gate runner.
 *   gates [--repo DIR] [--staged]            run every gate except issue-policy
 *   gate <name> [--repo DIR] [--staged] ...   run one gate; extra args go to the gate
 * Exit 0 when clean, 1 on violations, 2 on usage or configuration errors.
 */

import { resolve } from 'node:path'
import { Ctx, type Gate, type Violation } from './lib/context.ts'
import { GATES } from './gates/index.ts'

function usage(): never {
  console.error(`usage:
  tianshu-gates gates [--repo DIR] [--staged]
  tianshu-gates gate <name> [--repo DIR] [--staged] [gate args]
gates: ${GATES.map(gate => gate.name).join(', ')}`)
  process.exit(2)
}

interface Parsed {
  command: string
  name?: string
  repo: string
  staged: boolean
  rest: string[]
}

function parse(argv: string[]): Parsed {
  const [command, ...tail] = argv
  if (command !== 'gates' && command !== 'gate') usage()
  let repo = process.cwd()
  let staged = false
  const positional: string[] = []
  for (let index = 0; index < tail.length; index += 1) {
    const arg = tail[index] ?? ''
    if (arg === '--repo') {
      const value = tail[index + 1]
      if (value === undefined) usage()
      repo = resolve(value)
      index += 1
    } else if (arg === '--staged') {
      staged = true
    } else {
      positional.push(arg)
    }
  }
  if (command === 'gates') return { command, repo, staged, rest: positional }
  const [name, ...rest] = positional
  if (name === undefined) usage()
  return { command, name, repo, staged, rest }
}

function printViolations(name: string, violations: Violation[]): void {
  for (const v of violations) console.error(`${v.file}:${v.line} ${v.rule} ${v.message}`)
  console.error(`${name}: ${violations.length} violation(s)`)
}

async function main(): Promise<number> {
  const parsed = parse(process.argv.slice(2))
  const selected: Gate[] = parsed.command === 'gates'
    ? GATES.filter(gate => gate.runAll)
    : [GATES.find(gate => gate.name === parsed.name) ?? usage()]
  const ctx = new Ctx(parsed.repo, parsed.staged)

  let failed = 0
  for (const gate of selected) {
    // Gates whose own args carry flags (e.g. translation-pairing --write) receive everything after the name.
    const violations = await gate.run(ctx, parsed.command === 'gate' ? parsed.rest : [])
    if (violations.length > 0) {
      failed += 1
      printViolations(gate.name, violations)
    } else {
      console.log(`${gate.name}: ok`)
    }
  }
  // Notices come from config loading and from gates that skipped a check, so they print after the run.
  for (const notice of ctx.notices) console.error(`note: ${notice}`)
  return failed > 0 ? 1 : 0
}

main().then(code => { process.exitCode = code }, (error: unknown) => {
  console.error(`tianshu-gates: ${error instanceof Error ? error.message : String(error)}`)
  process.exitCode = 2
})
