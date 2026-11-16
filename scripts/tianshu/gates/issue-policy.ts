/** New for Tianshu (no deepseek-harness counterpart): PR/MR body must reference an Issue, and the PR/MR and every referenced Issue carry the label set. */
// Notes: .agents/notes/implemented/process/2026-11-02-unified-label-scheme.md,
//        .agents/notes/implemented/process/2026-11-02-referenced-issue-labels.md

import { violation, type Ctx, type Gate, type Violation } from '../lib/context.ts'

/** Same-repository Issue reference: `Fixes|Closes|Resolves|Refs #N`, case-insensitive. */
const ISSUE_REFERENCE = /\b(?:fixes|closes|resolves|refs)\s*:?\s*#(\d+)\b/gi

/** Body text that does not count as a reference: fenced blocks, HTML comments, inline code. */
export function visibleBody(body: string): string {
  const lines = body.split('\n')
  const kept: string[] = []
  let fence: string | undefined
  for (const line of lines) {
    const marker = /^\s*(`{3,}|~{3,})/.exec(line)?.[1]
    if (fence !== undefined) {
      if (marker !== undefined && marker[0] === fence[0] && marker.length >= fence.length) fence = undefined
      continue
    }
    if (marker !== undefined) {
      fence = marker
      continue
    }
    kept.push(line)
  }
  return kept.join('\n')
    .replace(/<!--[\s\S]*?-->/g, '')
    .replace(/`[^`\n]*`/g, '')
}

/** Issue numbers referenced from the visible body, in order, without duplicates. */
export function referencedIssues(body: string): number[] {
  const numbers = [...visibleBody(body).matchAll(ISSUE_REFERENCE)].map(match => Number(match[1]))
  return [...new Set(numbers)]
}

/**
 * The closed label families of the one scheme every project uses (Issue #40); kit/labels.json lists the same names.
 * `area/*` is open: any lowercase kebab-case name. Labels outside these families (GitHub defaults and the like) pass.
 */
export const LABEL_FAMILIES: Readonly<Record<string, readonly string[]>> = {
  type: ['feature', 'bug', 'doc', 'testing', 'cleanup', 'dependency', 'risk', 'acceptance', 'training'],
  severity: ['S1', 'S2', 'S3'],
  env: ['prod', 'test'],
  priority: ['p0', 'p1', 'p2', 'p3'],
  stage: ['rework'],
  agent: ['auto'],
  status: ['needs-owner'],
}

const AREA = /^area\/[a-z0-9]+(?:-[a-z0-9]+)*$/

/** The new name of a label from a retired scheme (kit `kind/*` and `p0`-`p3`, company `type::*` and friends), or undefined. */
export function retiredLabel(label: string): string | undefined {
  const kind: Record<string, string> = { 'bug-fix': 'bug', bug: 'bug', documentation: 'doc', process: 'cleanup' }
  if (label.startsWith('kind/')) {
    const value = label.slice('kind/'.length)
    return `type/${kind[value] ?? value}`
  }
  if (/^p[0-3]$/.test(label)) return `priority/${label}`
  const scoped = /^(type|severity|env|stage|priority)::(.+)$/.exec(label)
  return scoped ? `${scoped[1]}/${scoped[2]}` : undefined
}

/**
 * Check one label set; `file` and `prefix` name the owner in each violation.
 * A PR/MR (`change`) also needs an `area/*` label; an Issue does not.
 */
export function checkLabels(labels: readonly string[], file: string, prefix = '', change = true): Violation[] {
  const out: Violation[] = []
  const add = (rule: string, message: string): void => { out.push(violation(file, 0, `${prefix}${rule}`, message)) }
  const family = (name: string): string[] => labels.filter(label => label.startsWith(`${name}/`))
  for (const label of labels) {
    const renamed = retiredLabel(label)
    if (renamed !== undefined) {
      add('retired-label', `${label} is retired; use ${renamed}`)
      continue
    }
    const slash = label.indexOf('/')
    const allowed = slash > 0 ? LABEL_FAMILIES[label.slice(0, slash)] : undefined
    if (allowed !== undefined && !allowed.includes(label.slice(slash + 1))) add('unknown-label', `${label} is not in kit/labels.json`)
    if (label.startsWith('area/') && !AREA.test(label)) add('unknown-label', `${label} is not a lowercase kebab-case area/* name`)
  }
  const types = family('type')
  if (types.length !== 1) add('type-label', `exactly one type/* label is required, found ${types.length}`)
  const severities = family('severity')
  const envs = family('env')
  if (types.includes('type/bug')) {
    if (severities.length !== 1) add('bug-labels', `type/bug needs exactly one severity/S1-S3 label, found ${severities.length}`)
    if (envs.length !== 1) add('bug-labels', `type/bug needs exactly one env/prod or env/test label, found ${envs.length}`)
  } else {
    // Other types may carry one of each, e.g. the handbook's type/risk + severity/S1 (Issue #42).
    if (severities.length > 1) add('bug-labels', `at most one severity/* label, found ${severities.join(', ')}`)
    if (envs.length > 1) add('bug-labels', `at most one env/* label, found ${envs.join(', ')}`)
  }
  const priorities = family('priority')
  if (priorities.length > 1) add('priority-label', `at most one priority/* label, found ${priorities.join(', ')}`)
  if (change && family('area').length === 0) add('area-label', 'a PR/MR needs at least one area/* label')
  return out
}

/** What the platform returned for one referenced number: its labels, or why it does not count as an Issue. */
export type IssueLookup = { labels: string[] } | { missing: 'not-found' | 'pull-request' } | { error: string }

/**
 * Check one PR/MR body and its labels against the policy; returns violations.
 * `issues` holds the lookup for each referenced number; omit it to skip the Issue checks (outside CI).
 */
export function checkIssuePolicy(body: string, labels: readonly string[], issues?: ReadonlyMap<number, IssueLookup>): Violation[] {
  const out: Violation[] = []
  const refs = referencedIssues(body)
  if (refs.length === 0) {
    out.push(violation('TIANSHU_PR_BODY', 0, 'issue-ref', 'at least one same-repository Issue reference (Fixes|Closes|Resolves|Refs #N) is required outside comments and code'))
  }
  out.push(...checkLabels(labels, 'TIANSHU_PR_LABELS'))
  if (issues === undefined) return out
  for (const number of refs) {
    const file = `Issue #${number}`
    const found = issues.get(number)
    if (found === undefined || 'error' in found) {
      out.push(violation(file, 0, 'issue-read', `cannot read the Issue${found ? `: ${found.error}` : ''}; give the job a token that can read Issues (TIANSHU_API_TOKEN)`))
    } else if ('missing' in found) {
      out.push(violation(file, 0, 'issue-ref', found.missing === 'pull-request' ? 'refers to a pull request, not an Issue' : 'no such Issue in this repository'))
    } else {
      out.push(...checkLabels(found.labels, file, 'issue-', false))
    }
  }
  return out
}

/** Where and how to read Issues in CI; undefined outside a supported CI job. */
export interface IssueApi {
  platform: 'gitlab' | 'github'
  url: (number: number) => string
  headers: Record<string, string>
}

export function issueApiFromEnv(env: NodeJS.ProcessEnv): IssueApi | undefined {
  const override = env.TIANSHU_API_TOKEN
  if (env.CI_API_V4_URL && env.CI_PROJECT_ID) {
    const base = `${env.CI_API_V4_URL}/projects/${encodeURIComponent(env.CI_PROJECT_ID)}/issues/`
    const headers: Record<string, string> = override ? { 'PRIVATE-TOKEN': override } : env.CI_JOB_TOKEN ? { 'JOB-TOKEN': env.CI_JOB_TOKEN } : {}
    return { platform: 'gitlab', url: number => base + number, headers }
  }
  if (env.GITHUB_API_URL && env.GITHUB_REPOSITORY) {
    const token = override ?? env.GITHUB_TOKEN
    const headers: Record<string, string> = { Accept: 'application/vnd.github+json', ...(token ? { Authorization: `Bearer ${token}` } : {}) }
    return { platform: 'github', url: number => `${env.GITHUB_API_URL}/repos/${env.GITHUB_REPOSITORY}/issues/${number}`, headers }
  }
  return undefined
}

/** Look up one referenced number. Never throws: a failure becomes an `error` lookup, which the policy reports. */
export async function lookupIssue(api: IssueApi, number: number, fetcher: typeof fetch = fetch): Promise<IssueLookup> {
  try {
    const response = await fetcher(api.url(number), { headers: api.headers, signal: AbortSignal.timeout(15_000) })
    if (response.status === 404) return { missing: 'not-found' }
    if (!response.ok) return { error: `HTTP ${response.status}` }
    const data = await response.json() as { labels?: unknown, pull_request?: unknown }
    if (api.platform === 'github' && data.pull_request !== undefined) return { missing: 'pull-request' }
    const raw = Array.isArray(data.labels) ? data.labels : []
    // GitLab returns label names; GitHub returns objects with a name.
    const labels = raw.map(label => typeof label === 'string' ? label : String((label as { name?: unknown }).name ?? '')).filter(name => name !== '')
    return { labels }
  } catch (error) {
    return { error: error instanceof Error ? error.message : String(error) }
  }
}

export const issuePolicy: Gate = {
  name: 'issue-policy',
  summary: 'PR/MR body references an Issue; one type/* (a bug also severity/* and env/*), at most one priority/*, and area/* on the PR/MR; the same minus area on every referenced Issue',
  runAll: false,
  async run(ctx: Ctx) {
    const body = process.env.TIANSHU_PR_BODY
    const labels = process.env.TIANSHU_PR_LABELS
    if (body === undefined || labels === undefined) {
      throw new Error('issue-policy needs TIANSHU_PR_BODY and TIANSHU_PR_LABELS (comma-separated) in the environment')
    }
    const names = labels.split(',').map(label => label.trim()).filter(label => label !== '')
    const api = issueApiFromEnv(process.env)
    if (api === undefined) {
      ctx.notice?.('issue-policy: no GitLab or GitHub CI variables, so the referenced Issues were not checked')
      return checkIssuePolicy(body, names)
    }
    const issues = new Map<number, IssueLookup>()
    for (const number of referencedIssues(body)) issues.set(number, await lookupIssue(api, number))
    return checkIssuePolicy(body, names, issues)
  },
}
