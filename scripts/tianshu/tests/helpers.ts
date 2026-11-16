import { execFileSync } from 'node:child_process'
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import { Ctx } from '../lib/context.ts'

export interface Repo {
  root: string
  git: (args: string[]) => string
  ctx: (staged?: boolean) => Ctx
  write: (rel: string, text: string) => void
  stage: (rel: string) => void
  cleanup: () => void
}

/** Temporary repository with the given files; git-initialized and committed unless told otherwise. */
export function makeRepo(files: Record<string, string>, options: { git?: boolean; commit?: boolean } = {}): Repo {
  const root = mkdtempSync(join(tmpdir(), 'tianshu-gates-'))
  const git = (args: string[]): string => execFileSync('git', ['-C', root, ...args], {
    encoding: 'utf8',
    env: {
      ...process.env,
      GIT_AUTHOR_NAME: 'tianshu-test',
      GIT_AUTHOR_EMAIL: 'tianshu-test@example.invalid',
      GIT_COMMITTER_NAME: 'tianshu-test',
      GIT_COMMITTER_EMAIL: 'tianshu-test@example.invalid',
    },
    stdio: ['ignore', 'pipe', 'pipe'],
  }).trim()
  const write = (rel: string, text: string): void => {
    mkdirSync(dirname(join(root, rel)), { recursive: true })
    writeFileSync(join(root, rel), text)
  }
  for (const [rel, text] of Object.entries(files)) write(rel, text)
  if (options.git !== false) {
    git(['init', '-q'])
    if (options.commit !== false) {
      git(['add', '-A'])
      git(['commit', '-q', '--allow-empty', '-m', 'fixture'])
    }
  }
  return {
    root,
    git,
    ctx: (staged = false) => new Ctx(root, staged),
    write,
    stage: (rel: string) => {
      git(['add', '--', rel])
    },
    cleanup: () => rmSync(root, { recursive: true, force: true }),
  }
}

/** Shorthand: the rule names of a violation list, for compact assertions. */
export function rules(violations: { rule: string }[]): string[] {
  return violations.map(v => v.rule)
}
