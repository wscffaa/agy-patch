/** Project-side configuration read from `.tianshu/config.json`; every field has a default. */

import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'

export const CONFIG_PATH = '.tianshu/config.json'

export interface TianshuConfig {
  scope: {
    /** Extra glob patterns excluded from every gate, on top of the defaults. */
    exclude: string[]
  }
  repositoryReferences: {
    /** GitHub organizations whose URLs are rejected, e.g. `acme-old`. Empty disables the URL check. */
    forbiddenOrganizations: string[]
    /** Lowercase URL prefixes exempt from the organization check, e.g. `github.com/acme/kit`. */
    allowedUrlPrefixes: string[]
  }
  translation: {
    /** Bilingual pairing is opt-in; disabled projects skip the gate. */
    enabled: boolean
    sourceLanguage: string
    counterpartLanguage: string
    /** Source paths (or `dir/` prefixes) exempt from pairing. */
    exclude: string[]
    /** Extra source paths (or `dir/` prefixes) paired in addition to READMEs, root documents, `.agents/notes/`, and `docs/`. */
    include: string[]
    /** Directory prefixes holding a vendored project tree; the corpus scope applies below each prefix (e.g. `kit/template/`). */
    roots: string[]
    /** Optional `https://github.com/<org>/<repo>/blob/<branch>/` prefix that counts as a switcher target. */
    repositoryBlobRoot: string | null
  }
  agentNotes: {
    /** Pre-format notes dated before this `yyyy-mm-dd` may carry the grandfather comment; null accepts none. */
    legacyCutoff: string | null
  }
}

export const DEFAULT_CONFIG: TianshuConfig = {
  scope: { exclude: [] },
  repositoryReferences: { forbiddenOrganizations: [], allowedUrlPrefixes: [] },
  translation: {
    enabled: false,
    sourceLanguage: 'en',
    counterpartLanguage: 'zh',
    exclude: [],
    include: [],
    roots: [],
    repositoryBlobRoot: null,
  },
  agentNotes: { legacyCutoff: null },
}

function stringArray(value: unknown, field: string, fallback: string[]): string[] {
  if (value === undefined) return fallback
  if (!Array.isArray(value) || !value.every(entry => typeof entry === 'string')) {
    throw new Error(`${CONFIG_PATH}: ${field} must be an array of strings`)
  }
  return value
}

/**
 * Load `.tianshu/config.json` from the working tree, merging each section over the defaults.
 * A missing file yields the defaults plus a notice; malformed JSON or wrong field types throw.
 */
export function loadConfig(root: string): { config: TianshuConfig; notices: string[] } {
  const path = join(root, CONFIG_PATH)
  if (!existsSync(path)) {
    return {
      config: structuredClone(DEFAULT_CONFIG),
      notices: [`${CONFIG_PATH} not found; using defaults (translation pairing disabled, no forbidden organizations)`],
    }
  }
  let raw: unknown
  try {
    raw = JSON.parse(readFileSync(path, 'utf8'))
  } catch (error) {
    throw new Error(`${CONFIG_PATH}: invalid JSON (${error instanceof Error ? error.message : String(error)})`)
  }
  const section = (name: keyof TianshuConfig): Record<string, unknown> => {
    const value = (raw as Record<string, unknown>)[name]
    return typeof value === 'object' && value !== null && !Array.isArray(value) ? value as Record<string, unknown> : {}
  }
  const d = DEFAULT_CONFIG
  const scope = section('scope')
  const refs = section('repositoryReferences')
  const translation = section('translation')
  const notes = section('agentNotes')
  const config: TianshuConfig = {
    scope: { exclude: stringArray(scope.exclude, 'scope.exclude', d.scope.exclude) },
    repositoryReferences: {
      forbiddenOrganizations: stringArray(refs.forbiddenOrganizations, 'repositoryReferences.forbiddenOrganizations', []),
      allowedUrlPrefixes: stringArray(refs.allowedUrlPrefixes, 'repositoryReferences.allowedUrlPrefixes', []),
    },
    translation: {
      enabled: translation.enabled === undefined ? d.translation.enabled : translation.enabled === true,
      sourceLanguage: typeof translation.sourceLanguage === 'string' ? translation.sourceLanguage : d.translation.sourceLanguage,
      counterpartLanguage: typeof translation.counterpartLanguage === 'string'
        ? translation.counterpartLanguage
        : d.translation.counterpartLanguage,
      exclude: stringArray(translation.exclude, 'translation.exclude', []),
      include: stringArray(translation.include, 'translation.include', []),
      roots: stringArray(translation.roots, 'translation.roots', []),
      repositoryBlobRoot: typeof translation.repositoryBlobRoot === 'string' ? translation.repositoryBlobRoot : null,
    },
    agentNotes: {
      legacyCutoff: typeof notes.legacyCutoff === 'string' ? notes.legacyCutoff : null,
    },
  }
  return { config, notices: [] }
}
