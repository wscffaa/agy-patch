/** Adapted from deepseek-ai/deepseek-harness (MIT), scripts/verify-archived-agent-notes.ts. Manifest moved to .tianshu/; Figma seal exceptions removed. */

import { mkdirSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { AGENT_NOTE_CLASSES } from '../lib/agent-note-tree.ts'
import {
  extendArchiveManifest,
  parseArchiveManifest,
  renderArchiveManifest,
  validateArchiveArtifacts,
  validateArchiveManifestExtension,
  type ArchiveManifest,
} from '../lib/archive.ts'
import { violation, type Gate, type Violation } from '../lib/context.ts'

const ARCHIVE_ROOT = '.agents/notes/archived'
export const ARCHIVE_MANIFEST = '.tianshu/archived-notes.manifest.json'
const ALLOWED_ROOT_FILES = new Set(['AGENTS.md', '.gitkeep'])
const EMPTY: ArchiveManifest = { version: 1, files: {} }

/** Write the manifest with `--write`, after checking existing seals are unchanged. */
function sealArchive(root: string, rendered: string): void {
  mkdirSync(dirname(join(root, ARCHIVE_MANIFEST)), { recursive: true })
  writeFileSync(join(root, ARCHIVE_MANIFEST), rendered)
}

export const archivedAgentNotes: Gate = {
  name: 'archived-agent-notes',
  summary: 'frozen archive: triplet shape, archive metadata, sealed hashes',
  runAll: true,
  run(ctx, args) {
    const write = args.includes('--write')
    if (write && ctx.staged) throw new Error('--write cannot be combined with --staged')
    const prefix = `${ARCHIVE_ROOT}/`
    const errors: Violation[] = []
    const fail = (file: string, message: string): void => {
      errors.push(violation(file, 0, 'archived-agent-notes', message))
    }

    const archived = ctx.list([`${ARCHIVE_ROOT}/**/*`])
    const artifacts = new Map<string, Buffer>()
    for (const file of archived) {
      const rel = file.slice(prefix.length)
      if (!rel.includes('/')) {
        if (!ALLOWED_ROOT_FILES.has(rel)) fail(file, 'unexpected root file in the archive')
        continue
      }
      const kind = rel.split('/')[0] ?? ''
      if (!(AGENT_NOTE_CLASSES as readonly string[]).includes(kind)) {
        fail(file, `unknown Agent Note kind folder "${kind}"`)
        continue
      }
      const content = ctx.read(file)
      if (content !== undefined) artifacts.set(rel, content)
    }
    if (artifacts.size > 0 && !ctx.list([`${ARCHIVE_ROOT}/AGENTS.md`]).length) {
      fail(`${ARCHIVE_ROOT}/AGENTS.md`, 'archived/AGENTS.md is required when the archive holds notes')
    }
    for (const message of validateArchiveArtifacts(artifacts)) fail(ARCHIVE_ROOT, message)

    let manifest: ArchiveManifest = EMPTY
    const manifestText = ctx.text(ARCHIVE_MANIFEST)
    if (manifestText !== undefined) {
      try {
        manifest = parseArchiveManifest(manifestText)
      } catch (error: unknown) {
        fail(ARCHIVE_MANIFEST, error instanceof Error ? error.message : String(error))
      }
    } else if (!write && artifacts.size > 0) {
      fail(ARCHIVE_MANIFEST, 'manifest is required; seal new artifacts with `gate archived-agent-notes --write`')
    }

    const headText = ctx.headText(ARCHIVE_MANIFEST)
    const baseline = headText === undefined ? EMPTY : parseArchiveManifest(headText)
    for (const message of validateArchiveManifestExtension(baseline, manifest)) fail(ARCHIVE_MANIFEST, message)

    const extended = extendArchiveManifest(manifest, artifacts)
    for (const message of extended.errors) fail(ARCHIVE_MANIFEST, message)
    if (!write) {
      for (const path of extended.added) fail(`${ARCHIVE_ROOT}/${path}`, 'archived artifact is not sealed in the manifest')
      // Archive-level findings have no single file, so under --staged they count only when the archive or its manifest is staged.
      const relevant = !ctx.staged || ctx.touchesStaged([ARCHIVE_ROOT, ARCHIVE_MANIFEST])
      return relevant ? errors : []
    }
    if (errors.length > 0) return errors
    const rendered = renderArchiveManifest(extended.files)
    if (manifestText !== rendered) sealArchive(ctx.root, rendered)
    ctx.notice(`archived-agent-notes: sealed ${extended.added.length} new artifact(s); existing seals unchanged`)
    return []
  },
}
