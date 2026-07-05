'use client'

import { useEffect, useState } from 'react'
import type { ConflictConfig, ConflictVariableConfig, StudyVariableDef } from '@/lib/api'

interface Props {
  reportTypes: string[]
  variables: StudyVariableDef[]
  config: ConflictConfig
  busy?: boolean
  onSave: (config: ConflictConfig) => void
}

const EMPTY_VAR: ConflictVariableConfig = { strategy: 'none', ranking: [], date_pref: 'earliest' }

export default function ConflictSettingsPanel({ reportTypes, variables, config, busy, onSave }: Props) {
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState<ConflictConfig>(() => structuredClone(config))

  // Re-sync the local draft when the incoming config changes (e.g. switching the
  // study selector, or after a save recomputes the report) — otherwise the panel
  // would show and could re-save a stale config from a different study.
  useEffect(() => {
    setDraft(structuredClone(config))
  }, [config])

  const varCfg = (key: string): ConflictVariableConfig => draft.per_variable[key] ?? EMPTY_VAR

  const update = (key: string, patch: Partial<ConflictVariableConfig>) => {
    setDraft((d) => ({
      ...d,
      per_variable: { ...d.per_variable, [key]: { ...varCfg(key), ...patch } },
    }))
  }

  const moveRank = (key: string, idx: number, dir: -1 | 1) => {
    const r = [...varCfg(key).ranking]
    const j = idx + dir
    if (j < 0 || j >= r.length) return
    ;[r[idx], r[j]] = [r[j], r[idx]]
    update(key, { ranking: r })
  }
  const addRank = (key: string, rt: string) => {
    if (!rt) return
    const r = varCfg(key).ranking
    if (!r.includes(rt)) update(key, { ranking: [...r, rt] })
  }
  const removeRank = (key: string, rt: string) => {
    update(key, { ranking: varCfg(key).ranking.filter((x) => x !== rt) })
  }

  return (
    <div className="rounded-lg border border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-800">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between px-4 py-3 text-left"
      >
        <span className="text-sm font-semibold text-gray-900 dark:text-gray-100">
          Automatic conflict resolution
          <span className={`ml-2 rounded px-2 py-0.5 text-xs font-medium ${
            draft.enabled
              ? 'bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-200'
              : 'bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300'
          }`}>
            {draft.enabled ? 'On' : 'Off'}
          </span>
        </span>
        <span className="text-gray-400">{open ? '▲' : '▼'}</span>
      </button>

      {open && (
        <div className="space-y-4 border-t border-gray-100 px-4 py-4 dark:border-gray-700">
          <label className="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-200">
            <input
              type="checkbox"
              checked={draft.enabled}
              onChange={(e) => setDraft((d) => ({ ...d, enabled: e.target.checked }))}
            />
            Auto-resolve conflicts using the rules below (auto-confirms; reviewer can override)
          </label>

          {draft.enabled && variables.map((v) => {
            const cfg = varCfg(v.key)
            const available = reportTypes.filter((rt) => !cfg.ranking.includes(rt))
            return (
              <div key={v.key} className="rounded border border-gray-200 p-3 dark:border-gray-700">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm font-medium text-gray-800 dark:text-gray-100">{v.label}</span>
                  <select
                    value={cfg.strategy}
                    onChange={(e) => update(v.key, { strategy: e.target.value as ConflictVariableConfig['strategy'] })}
                    className="rounded border border-gray-300 px-2 py-1 text-xs dark:border-gray-600 dark:bg-gray-900 dark:text-gray-100"
                  >
                    <option value="none">Manual (no auto-resolution)</option>
                    <option value="report_type_ranking">Report-type ranking</option>
                    <option value="date">By date</option>
                  </select>
                </div>

                {cfg.strategy === 'report_type_ranking' && (
                  <div className="mt-2">
                    <p className="mb-1 text-xs text-gray-500">Priority order (highest first):</p>
                    {cfg.ranking.length === 0 && (
                      <p className="text-xs italic text-gray-400">No report types ranked yet — add below.</p>
                    )}
                    <ol className="space-y-1">
                      {cfg.ranking.map((rt, idx) => (
                        <li key={rt} className="flex items-center gap-2 text-xs">
                          <span className="w-4 text-gray-400">{idx + 1}.</span>
                          <span className="flex-1 rounded bg-gray-100 px-2 py-0.5 dark:bg-gray-700 dark:text-gray-100">{rt}</span>
                          <button onClick={() => moveRank(v.key, idx, -1)} className="px-1 text-gray-400 hover:text-gray-700">↑</button>
                          <button onClick={() => moveRank(v.key, idx, 1)} className="px-1 text-gray-400 hover:text-gray-700">↓</button>
                          <button onClick={() => removeRank(v.key, rt)} className="px-1 text-red-400 hover:text-red-600">✕</button>
                        </li>
                      ))}
                    </ol>
                    {available.length > 0 && (
                      <select
                        value=""
                        onChange={(e) => { addRank(v.key, e.target.value); e.target.value = '' }}
                        className="mt-2 rounded border border-gray-300 px-2 py-1 text-xs dark:border-gray-600 dark:bg-gray-900 dark:text-gray-100"
                      >
                        <option value="">+ add report type…</option>
                        {available.map((rt) => <option key={rt} value={rt}>{rt}</option>)}
                      </select>
                    )}
                  </div>
                )}

                {cfg.strategy === 'date' && (
                  <div className="mt-2 flex items-center gap-2 text-xs">
                    <span className="text-gray-500">Pick the</span>
                    <select
                      value={cfg.date_pref}
                      onChange={(e) => update(v.key, { date_pref: e.target.value as 'earliest' | 'latest' })}
                      className="rounded border border-gray-300 px-2 py-1 dark:border-gray-600 dark:bg-gray-900 dark:text-gray-100"
                    >
                      <option value="earliest">earliest (initial diagnosis)</option>
                      <option value="latest">latest (most recent)</option>
                    </select>
                    <span className="text-gray-500">dated value</span>
                  </div>
                )}
              </div>
            )
          })}

          <div className="flex items-center gap-2">
            <button
              onClick={() => onSave(draft)}
              disabled={busy}
              className="rounded bg-primary-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-primary-700 disabled:opacity-50"
            >
              {busy ? 'Applying…' : 'Apply & recompute'}
            </button>
            <p className="text-xs text-gray-400">
              Ties (top report type disagrees / dates equal) are sent to manual review.
            </p>
          </div>
        </div>
      )}
    </div>
  )
}
