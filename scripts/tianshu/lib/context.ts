/** Shared repository access for every gate: one selected content plane (working tree or Git index). */

import { execFileSync } from 'node:child_process'
import { existsSync, readdirSync, readFileSync, realpathSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { loadConfig, type TianshuConfig } from './config.ts'

/** One rule violation, printed as `file:line rule message`. */
export interface Violation {
  file: string
  line: number
  rule: string
  message: string
}

/** A gate: pure over the context except where noted, returns violations (empty means pass). */
export interface Gate {
  name: string
  summary: string
  /** False for gates that need external input and are not part of `gates`. */
  runAll: boolean
  /** Gates that read a remote API (issue-policy) return a Promise. */
  run: (ctx: Ctx, args: string[]) => Violation[] | Promise<Violation[]>
}

/** Paths never scanned by any gate. Projects extend this via `scope.exclude`. */
export const DEFAULT_EXCLUDE = ['**/node_modules/**', '**/.git/**', '**/scripts/tianshu/**']

/** Dot-inclusive glob to RegExp: a double-star directory segment spans zero or more directories; `*` and `?` stay in one segment. */
export function globToRegExp(pattern: string): RegExp {
  let expression = ''
  for (let index = 0; index < pattern.length; index += 1) {
    const char = pattern[index] ?? ''
    if (pattern.startsWith('**/', index)) {
      expression += '(?:.*/)?'
      index += 2
    } else if (pattern.startsWith('**', index)) {
      expression += '.*'
      index += 1
    } else if (char === '*') expression += '[^/]*'
    else if (char === '?') expression += '[^/]'
    else expression += char.replace(/[.+^${}()|[\]\\]/g, '\\$&')
  }
  return new RegExp(`^${expression}$`)
}

function gitOutput(root: string, args: string[]): string {
  return execFileSync('git', ['-C', root, ...args], {
    encoding: 'utf8',
    maxBuffer: 1 << 30,
    stdio: ['ignore', 'pipe', 'pipe'],
  })
}

function isGitTopLevel(root: string): boolean {
  try {
    const top = gitOutput(root, ['rev-parse', '--show-toplevel']).trim()
    return realpathSync(top) === realpathSync(root)
  } catch {
    return false
  }
}

function walkFiles(root: string, rel = ''): string[] {
  const out: string[] = []
  for (const entry of readdirSync(join(root, rel), { withFileTypes: true })) {
    if (entry.name === '.git' || entry.name === 'node_modules') continue
    const child = rel === '' ? entry.name : `${rel}/${entry.name}`
    if (entry.isDirectory()) out.push(...walkFiles(root, child))
    else if (entry.isFile()) out.push(child)
  }
  return out
}

/**
 * Repository view used by all gates. With `staged`, listings and contents come from
 * the Git index (what the commit will contain); otherwise from the working tree.
 * Config and manifests under `.tianshu/` are always read from the working tree.
 */
export class Ctx {
  readonly root: string
  readonly staged: boolean
  readonly isGit: boolean
  readonly config: TianshuConfig
  readonly notices: string[] = []
  private indexSet?: Set<string>
  private indexDirs?: Set<string>
  private stagedSet?: Set<string>
  private allCache?: string[]
  private blobs = new Map<string, Buffer | undefined>()

  constructor(root: string, staged: boolean) {
    this.root = root
    this.isGit = isGitTopLevel(root)
    if (staged && !this.isGit) throw new Error('--staged needs the target to be a Git repository root')
    this.staged = staged
    const loaded = loadConfig(root)
    this.config = loaded.config
    this.notices.push(...loaded.notices)
  }

  /** Repo-relative paths of every file in the selected plane, unfiltered. */
  private files(): string[] {
    if (this.allCache) return this.allCache
    if (this.staged) {
      this.allCache = [...this.index()]
    } else if (this.isGit) {
      const listed = gitOutput(this.root, ['ls-files', '-z', '--cached', '--others', '--exclude-standard'])
      this.allCache = listed.split('\0').filter(file => file !== '' && existsSync(join(this.root, file)))
    } else {
      this.allCache = walkFiles(this.root)
    }
    return this.allCache
  }

  private index(): Set<string> {
    if (this.indexSet) return this.indexSet
    const paths = gitOutput(this.root, ['ls-files', '-z', '--cached']).split('\0').filter(file => file !== '')
    this.indexSet = new Set(paths)
    this.indexDirs = new Set<string>()
    for (const path of paths) {
      for (let slash = path.indexOf('/'); slash !== -1; slash = path.indexOf('/', slash + 1)) {
        this.indexDirs.add(path.slice(0, slash))
      }
    }
    return this.indexSet
  }

  /** Files in the selected plane matching any pattern and no exclusion, sorted. */
  list(patterns: readonly string[], extraExclude: readonly string[] = []): string[] {
    const include = patterns.map(globToRegExp)
    const exclude = [...DEFAULT_EXCLUDE, ...this.config.scope.exclude, ...extraExclude].map(globToRegExp)
    return this.files()
      .filter(file => include.some(re => re.test(file)) && !exclude.some(re => re.test(file)))
      .sort()
  }

  /** Whether a file or directory exists in the selected plane. */
  exists(rel: string): boolean {
    const path = rel.replace(/\/+$/, '')
    if (!this.staged) return existsSync(join(this.root, path))
    return this.index().has(path) || (this.indexDirs?.has(path) ?? false)
  }

  /** Bytes of one file in the selected plane, or undefined when absent. */
  read(rel: string): Buffer | undefined {
    if (this.blobs.has(rel)) return this.blobs.get(rel)
    let content: Buffer | undefined
    if (this.staged) {
      content = this.index().has(rel)
        ? execFileSync('git', ['-C', this.root, 'cat-file', 'blob', `:${rel}`], { maxBuffer: 1 << 30 })
        : undefined
    } else {
      const path = join(this.root, rel)
      content = existsSync(path) && statSync(path).isFile() ? readFileSync(path) : undefined
    }
    this.blobs.set(rel, content)
    return content
  }

  /** UTF-8 text of one file in the selected plane, or undefined when absent. */
  text(rel: string): string | undefined {
    return this.read(rel)?.toString('utf8')
  }

  /** Whether a finding in this file should be reported (always true unless `--staged`). */
  inScope(rel: string): boolean {
    if (!this.staged) return true
    return this.stagedFiles().has(rel)
  }

  /** Whether any staged change, deletions included, lies under one of the prefixes. */
  touchesStaged(prefixes: readonly string[]): boolean {
    if (!this.staged) return true
    this.stagedFiles()
    return [...this.stagedAll].some(file => prefixes.some(prefix => file === prefix || file.startsWith(`${prefix}/`)))
  }

  private stagedAll = new Set<string>()

  private stagedFiles(): Set<string> {
    if (this.stagedSet === undefined) {
      const all = gitOutput(this.root, ['diff', '--cached', '--name-only', '-z']).split('\0').filter(file => file !== '')
      this.stagedAll = new Set(all)
      const added = gitOutput(this.root, ['diff', '--cached', '--name-only', '--diff-filter=ACMR', '-z'])
      this.stagedSet = new Set(added.split('\0').filter(file => file !== ''))
    }
    return this.stagedSet
  }

  /** A file's bytes at HEAD, or undefined when there is no HEAD or the file is absent there. */
  headText(rel: string): string | undefined {
    if (!this.isGit) return undefined
    try {
      return gitOutput(this.root, ['show', `HEAD:${rel}`])
    } catch {
      return undefined
    }
  }

  /** Record a non-failing message (skipped check, defaulted config) for the CLI to print on stderr. */
  notice(message: string): void {
    this.notices.push(message)
  }
}

/** Build a violation list entry for a gate. */
export function violation(file: string, line: number, rule: string, message: string): Violation {
  return { file, line, rule, message }
}
