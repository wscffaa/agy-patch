import assert from 'node:assert/strict'
import { describe, it } from 'node:test'
import { existsSync, readFileSync } from 'node:fs'
import { checkIssuePolicy, checkLabels, issueApiFromEnv, issuePolicy, LABEL_FAMILIES, lookupIssue, referencedIssues, type IssueLookup } from '../gates/issue-policy.ts'

const OK_LABELS = ['type/feature', 'area/cli', 'priority/p2']

describe('issue-policy', () => {
  it('passes a body with a closing reference and the required labels', () => {
    assert.deepEqual(checkIssuePolicy('Fixes #12', OK_LABELS), [])
  })

  it('accepts each closing keyword case-insensitively', () => {
    assert.deepEqual(checkIssuePolicy('closes #7', OK_LABELS), [])
    assert.deepEqual(checkIssuePolicy('Refs: #8', OK_LABELS), [])
  })

  it('reports a body with no Issue reference', () => {
    assert.ok(checkIssuePolicy('Some text', OK_LABELS).some(v => v.rule === 'issue-ref'))
  })

  it('ignores a reference inside an HTML comment, a fence, or inline code', () => {
    for (const body of ['<!-- Fixes #3 -->', '```\nFixes #3\n```', '`Fixes #3`']) {
      assert.ok(checkIssuePolicy(body, OK_LABELS).some(v => v.rule === 'issue-ref'), body)
    }
  })

  it('does not count a cross-repository reference', () => {
    assert.ok(checkIssuePolicy('Fixes other/repo#5', OK_LABELS).some(v => v.rule === 'issue-ref'))
  })

  it('requires exactly one type label', () => {
    assert.ok(checkIssuePolicy('Fixes #1', ['area/cli']).some(v => v.rule === 'type-label'))
    assert.ok(checkIssuePolicy('Fixes #1', ['type/feature', 'type/doc', 'area/cli']).some(v => v.rule === 'type-label'))
  })

  it('requires at least one area label on a PR/MR', () => {
    assert.deepEqual(checkIssuePolicy('Fixes #1', ['type/feature']).map(v => v.rule), ['area-label'])
  })

  it('requires exactly one severity and one env on a bug, and at most one of each otherwise', () => {
    assert.deepEqual(checkIssuePolicy('Closes #1', ['type/bug', 'severity/S1', 'env/prod', 'area/ci']), [])
    assert.deepEqual(checkIssuePolicy('Closes #1', ['type/bug', 'area/ci']).map(v => v.rule), ['bug-labels', 'bug-labels'])
    assert.deepEqual(checkIssuePolicy('Closes #1', ['type/bug', 'severity/S1', 'severity/S2', 'env/prod', 'area/ci']).map(v => v.rule), ['bug-labels'])
    assert.deepEqual(checkIssuePolicy('Closes #1', ['type/risk', 'severity/S1', 'area/ci']), [])
    assert.deepEqual(checkIssuePolicy('Closes #1', ['type/risk', 'severity/S1', 'severity/S2', 'area/ci']).map(v => v.rule), ['bug-labels'])
    assert.deepEqual(checkIssuePolicy('Closes #1', ['type/feature', 'env/prod', 'area/ci']), [])
    assert.deepEqual(checkIssuePolicy('Closes #1', ['type/feature', 'env/prod', 'env/test', 'area/ci']).map(v => v.rule), ['bug-labels'])
  })

  it('names the new label for every retired label', () => {
    const out = checkIssuePolicy('Fixes #1', ['kind/bug-fix', 'p1', 'type::bug', 'severity::S2', 'env::prod', 'stage::rework', 'kind/process', 'area/ci'])
    const retired = out.filter(v => v.rule === 'retired-label').map(v => v.message)
    assert.deepEqual(retired, [
      'kind/bug-fix is retired; use type/bug', 'p1 is retired; use priority/p1', 'type::bug is retired; use type/bug',
      'severity::S2 is retired; use severity/S2', 'env::prod is retired; use env/prod', 'stage::rework is retired; use stage/rework',
      'kind/process is retired; use type/cleanup',
    ])
    assert.ok(out.some(v => v.rule === 'type-label'))
  })

  it('rejects names outside the catalog in a closed family, and malformed areas', () => {
    assert.deepEqual(checkIssuePolicy('Fixes #1', ['type/docs', 'area/ci']).map(v => v.rule), ['unknown-label'])
    assert.deepEqual(checkIssuePolicy('Fixes #1', ['type/doc', 'area/CI', 'priority/p4']).map(v => v.rule), ['unknown-label', 'unknown-label'])
    assert.deepEqual(checkIssuePolicy('Fixes #1', ['type/doc', 'area/ci', 'good first issue', 'stage/rework']), [])
  })

  it('accepts the follow-up labels and names typos in their families (Issue #52)', () => {
    assert.deepEqual(checkLabels(['type/feature', 'agent/auto', 'status/needs-owner'], 'x', '', false), [])
    assert.deepEqual(checkLabels(['type/feature', 'agent/manual', 'status/needs_owner'], 'x', '', false).map(v => v.message),
      ['agent/manual is not in kit/labels.json', 'status/needs_owner is not in kit/labels.json'])
  })

  it('allows at most one priority label', () => {
    assert.ok(checkIssuePolicy('Fixes #1', [...OK_LABELS, 'priority/p1']).some(v => v.rule === 'priority-label'))
    assert.deepEqual(checkIssuePolicy('Fixes #1', ['type/feature', 'area/cli', 'priority/p0']), [])
  })

  it('keeps kit/labels.json and the gate catalog in step', () => {
    const file = new URL('../../labels.json', import.meta.url)
    if (!existsSync(file)) return // a vendored copy in a project has no kit/labels.json
    const names = (JSON.parse(readFileSync(file, 'utf8')) as Array<{ name: string }>).map(label => label.name)
    const closed = Object.entries(LABEL_FAMILIES).flatMap(([family, values]) => values.map(value => `${family}/${value}`))
    assert.deepEqual(names.filter(name => !name.startsWith('area/')).sort(), closed.sort())
    for (const name of names) assert.deepEqual(checkLabels([name], 'x').filter(v => v.rule === 'unknown-label' || v.rule === 'retired-label'), [], name)
  })

  it('collects referenced Issue numbers once, outside comments and code', () => {
    assert.deepEqual(referencedIssues('Closes #3\nRefs #4, fixes #3\n`Fixes #9`\n<!-- Refs #10 -->'), [3, 4])
  })

  const issues = (entries: Array<[number, IssueLookup]>): Map<number, IssueLookup> => new Map(entries)

  it('passes when every referenced Issue carries a valid label set', () => {
    const map = issues([[3, { labels: ['type/bug', 'severity/S2', 'env/prod'] }], [4, { labels: ['type/doc'] }]])
    assert.deepEqual(checkIssuePolicy('Closes #3\nRefs #4', ['type/bug', 'severity/S2', 'env/prod', 'area/ci'], map), [])
  })

  it('reports an unlabeled or half-labeled referenced Issue under its own name, without asking it for an area', () => {
    const out = checkIssuePolicy('Closes #16', OK_LABELS, issues([[16, { labels: [] }]]))
    assert.deepEqual(out.map(v => [v.file, v.rule]), [['Issue #16', 'issue-type-label']])
    const bug = checkIssuePolicy('Closes #3', OK_LABELS, issues([[3, { labels: ['type/bug'] }]]))
    assert.deepEqual(bug.map(v => v.rule), ['issue-bug-labels', 'issue-bug-labels'])
  })

  it('checks priority and retired labels on Issues too', () => {
    assert.deepEqual(checkIssuePolicy('Fixes #1', OK_LABELS, issues([[1, { labels: ['type/cleanup', 'area/ci'] }]])), [])
    assert.ok(checkIssuePolicy('Fixes #1', OK_LABELS, issues([[1, { labels: ['type/cleanup', 'priority/p0', 'priority/p1'] }]])).some(v => v.rule === 'issue-priority-label'))
    assert.ok(checkIssuePolicy('Fixes #1', OK_LABELS, issues([[1, { labels: ['kind/cleanup'] }]])).some(v => v.rule === 'issue-retired-label'))
  })

  it('reports a missing Issue, a pull request number, and an unreadable Issue', () => {
    const out = checkIssuePolicy('Closes #1\nRefs #2\nRefs #3', OK_LABELS,
      issues([[1, { missing: 'not-found' }], [2, { missing: 'pull-request' }], [3, { error: 'HTTP 401' }]]))
    assert.deepEqual(out.map(v => [v.file, v.rule]), [['Issue #1', 'issue-ref'], ['Issue #2', 'issue-ref'], ['Issue #3', 'issue-read']])
    assert.ok(out[2]?.message.includes('TIANSHU_API_TOKEN'))
  })

  it('skips the Issue checks when no lookup map is given (outside CI)', () => {
    assert.deepEqual(checkIssuePolicy('Closes #99', OK_LABELS), [])
  })

  it('builds the GitLab and GitHub Issue API from CI variables, preferring TIANSHU_API_TOKEN', () => {
    const gitlab = issueApiFromEnv({ CI_API_V4_URL: 'http://gl/api/v4', CI_PROJECT_ID: '7', CI_JOB_TOKEN: 'job' })
    assert.equal(gitlab?.url(5), 'http://gl/api/v4/projects/7/issues/5')
    assert.deepEqual(gitlab?.headers, { 'JOB-TOKEN': 'job' })
    assert.deepEqual(issueApiFromEnv({ CI_API_V4_URL: 'u', CI_PROJECT_ID: '7', CI_JOB_TOKEN: 'job', TIANSHU_API_TOKEN: 'pat' })?.headers, { 'PRIVATE-TOKEN': 'pat' })
    const github = issueApiFromEnv({ GITHUB_API_URL: 'https://api.github.com', GITHUB_REPOSITORY: 'o/r', GITHUB_TOKEN: 'gh' })
    assert.equal(github?.url(5), 'https://api.github.com/repos/o/r/issues/5')
    assert.equal(github?.headers.Authorization, 'Bearer gh')
    assert.equal(issueApiFromEnv({}), undefined)
  })

  it('maps API responses to lookups and never throws', async () => {
    const reply = (status: number, body: unknown) => (async () => new Response(JSON.stringify(body), { status })) as unknown as typeof fetch
    const gitlab = issueApiFromEnv({ CI_API_V4_URL: 'http://gl', CI_PROJECT_ID: '1', CI_JOB_TOKEN: 't' })!
    const github = issueApiFromEnv({ GITHUB_API_URL: 'http://gh', GITHUB_REPOSITORY: 'o/r' })!
    assert.deepEqual(await lookupIssue(gitlab, 1, reply(200, { labels: ['type/doc'] })), { labels: ['type/doc'] })
    assert.deepEqual(await lookupIssue(github, 1, reply(200, { labels: [{ name: 'type/doc' }] })), { labels: ['type/doc'] })
    assert.deepEqual(await lookupIssue(github, 1, reply(200, { labels: [], pull_request: {} })), { missing: 'pull-request' })
    assert.deepEqual(await lookupIssue(gitlab, 1, reply(404, {})), { missing: 'not-found' })
    assert.deepEqual(await lookupIssue(gitlab, 1, reply(403, {})), { error: 'HTTP 403' })
    const down = (async () => { throw new Error('ECONNREFUSED') }) as unknown as typeof fetch
    assert.deepEqual(await lookupIssue(gitlab, 1, down), { error: 'ECONNREFUSED' })
  })

  it('reads body and labels from the environment, fails loudly when they are missing, and checks Issues in CI', async () => {
    const keys = ['TIANSHU_PR_BODY', 'TIANSHU_PR_LABELS', 'CI_API_V4_URL', 'CI_PROJECT_ID', 'CI_JOB_TOKEN', 'TIANSHU_API_TOKEN', 'GITHUB_API_URL', 'GITHUB_REPOSITORY', 'GITHUB_TOKEN']
    const saved = Object.fromEntries(keys.map(key => [key, process.env[key]]))
    const savedFetch = globalThis.fetch
    const notices: string[] = []
    const ctx = { notice: (message: string) => { notices.push(message) } } as never
    try {
      for (const key of keys) delete process.env[key]
      await assert.rejects(async () => issuePolicy.run(ctx, []), /TIANSHU_PR_BODY/)
      process.env.TIANSHU_PR_BODY = 'Closes #4'
      process.env.TIANSHU_PR_LABELS = 'type/cleanup, area/gates'
      assert.deepEqual(await issuePolicy.run(ctx, []), [])
      assert.ok(notices.some(message => message.includes('not checked')))
      process.env.CI_API_V4_URL = 'http://gl/api/v4'
      process.env.CI_PROJECT_ID = '9'
      process.env.CI_JOB_TOKEN = 'job'
      const seen: string[] = []
      globalThis.fetch = (async (url: string) => { seen.push(url); return new Response(JSON.stringify({ labels: [] }), { status: 200 }) }) as unknown as typeof fetch
      const out = await issuePolicy.run(ctx, [])
      assert.deepEqual(seen, ['http://gl/api/v4/projects/9/issues/4'])
      assert.ok(out.some(v => v.file === 'Issue #4' && v.rule === 'issue-type-label'))
    } finally {
      globalThis.fetch = savedFetch
      for (const key of keys) {
        if (saved[key] === undefined) delete process.env[key]
        else process.env[key] = saved[key]
      }
    }
  })
})
