/** Adapted from deepseek-ai/deepseek-harness (MIT), scripts/verify-repository-references.ts and scripts/verify-public-repository-links.ts (canonicalReferenceText). Unavailable-repository check dropped; forbidden organizations are now configurable. */

import { execFileSync } from 'node:child_process'
import { violation, type Ctx, type Gate, type Violation } from '../lib/context.ts'

const ARCHIVE_EXCLUDE = ['.agents/notes/archived/**', 'vendor/**']

/** Decimal-only tokens collide with sizes and versions, so a candidate must contain a hex letter. */
const commitCandidate = /(?<![a-z0-9])(?=[\da-f]{0,39}[a-f])[\da-f]{7,40}(?![a-z0-9])/gi

const namedReferenceCharacters: Readonly<Record<string, string>> = {
  hyphen: '-',
  num: '#',
  period: '.',
  colon: ':',
  sol: '/',
}

/** Normalize escaped references (URL, JavaScript, HTML escapes, compatibility forms) to lowercase plain text. */
export function canonicalReferenceText(source: string): string {
  return source
    .normalize('NFKC')
    .replaceAll('\\/', '/')
    .replace(/\\(?:u([\da-f]{4})|x([\da-f]{2}))/gi, (_match, unicode: string | undefined, byte: string | undefined) =>
      String.fromCodePoint(Number.parseInt(unicode ?? byte ?? '', 16)))
    .replace(/%([\da-f]{2})/gi, (_match, code: string) => String.fromCodePoint(Number.parseInt(code, 16)))
    .replace(/&#(?:(\d+)|x([\da-f]+));/gi, (entity, decimal: string | undefined, hexadecimal: string | undefined) => {
      const code = Number.parseInt(decimal ?? hexadecimal ?? '', decimal === undefined ? 16 : 10)
      return code <= 0x10ffff ? String.fromCodePoint(code) : entity
    })
    .replace(/&(hyphen|num|period|colon|sol);/gi, (entity, name: string) => namedReferenceCharacters[name.toLowerCase()] ?? entity)
    .normalize('NFKC')
    .toLowerCase()
}

/** Unique object whose name starts with `prefix`, from a sorted object list; undefined when none or several. */
export function uniquePrefixMatch(objects: readonly string[], prefix: string): string | undefined {
  let low = 0
  let high = objects.length
  while (low < high) {
    const middle = (low + high) >>> 1
    if ((objects[middle] ?? prefix) < prefix) low = middle + 1
    else high = middle
  }
  const match = objects[low]
  if (match?.startsWith(prefix) !== true || objects[low + 1]?.startsWith(prefix) === true) return undefined
  return match
}

function git(root: string, args: string[], input?: string): string[] {
  const output = execFileSync('git', ['-C', root, ...args], {
    encoding: 'utf8',
    input,
    maxBuffer: 1 << 30,
    env: { ...process.env, GIT_NO_LAZY_FETCH: '1' },
    stdio: ['pipe', 'pipe', 'pipe'],
  }).trimEnd()
  return output === '' ? [] : output.split('\n')
}

/** Lowercase candidates that name exactly one local object which is a commit. Git object DB only; no network. */
function repositoryCommits(root: string, sources: readonly string[]): Set<string> {
  const candidates = [...new Set(sources.flatMap(source =>
    [...source.matchAll(commitCandidate)].map(match => match[0].toLowerCase())))]
  if (candidates.length === 0) return new Set()
  const objects = git(root, ['cat-file', '--batch-all-objects', '--batch-check=%(objectname)']).sort()
  const matches = new Map<string, string>()
  for (const candidate of candidates) {
    const object = uniquePrefixMatch(objects, candidate)
    if (object !== undefined) matches.set(candidate, object)
  }
  if (matches.size === 0) return new Set()
  const matched = [...new Set(matches.values())]
  const commits = new Set(git(root, ['cat-file', '--batch-check=%(objectname) %(objecttype)'], `${matched.join('\n')}\n`)
    .map(line => line.split(' '))
    .filter(([, type]) => type === 'commit')
    .map(([object]) => object))
  return new Set([...matches].filter(([, object]) => commits.has(object ?? '')).map(([candidate]) => candidate))
}

function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

export const repositoryReferences: Gate = {
  name: 'repository-references',
  summary: 'no commit-hash references or forbidden organization URLs in maintained files',
  runAll: true,
  run(ctx: Ctx) {
    const refs = ctx.config.repositoryReferences
    const orgPatterns = refs.forbiddenOrganizations.map(org =>
      new RegExp(`\\bgithub\\.com/${escapeRegExp(canonicalReferenceText(org))}(?![a-z0-9-])`))
    const exemptions = refs.allowedUrlPrefixes.map(prefix => canonicalReferenceText(prefix))

    const files = ctx.list(['**/*'], ARCHIVE_EXCLUDE)
    const sources = new Map<string, string>()
    for (const file of files) {
      const content = ctx.read(file)
      if (content === undefined || content.includes(0)) continue
      sources.set(file, content.toString('utf8'))
    }
    let commits = new Set<string>()
    if (ctx.isGit) {
      commits = repositoryCommits(ctx.root, [...sources.values()])
    } else {
      ctx.notice('repository-references: not a Git repository; commit-hash check skipped')
    }

    const out: Violation[] = []
    for (const [file, source] of sources) {
      if (!ctx.inScope(file)) continue
      for (const [index, line] of source.split('\n').entries()) {
        let canonical = canonicalReferenceText(line)
        for (const exemption of exemptions) canonical = canonical.split(exemption).join('')
        if (orgPatterns.some(pattern => pattern.test(canonical))) {
          out.push(violation(file, index + 1, 'organization-url', 'forbidden organization URL (see repositoryReferences.forbiddenOrganizations)'))
        }
        if ([...line.matchAll(commitCandidate)].some(match => commits.has(match[0].toLowerCase()))) {
          out.push(violation(file, index + 1, 'commit-hash', 'commit hash reference; use a release tag or a maintained repository link'))
        }
      }
    }
    return out
  },
}
