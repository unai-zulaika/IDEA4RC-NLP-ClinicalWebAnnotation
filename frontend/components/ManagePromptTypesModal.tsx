'use client'

import { useState } from 'react'
import type { SessionData, PromptInfo } from '@/lib/api'
import PresetSelector from '@/components/PresetSelector'

export interface ManagePromptTypesModalProps {
  session: SessionData
  availablePrompts: PromptInfo[]
  onClose: () => void
  onSave: (reportTypeMapping: Record<string, string[]>) => Promise<void>
  error: string | null
  center: string
}

export default function ManagePromptTypesModal({
  session,
  availablePrompts,
  onClose,
  onSave,
  error,
  center,
}: ManagePromptTypesModalProps) {
  const allPromptTypes = availablePrompts.map((p) => p.prompt_type)
  const [saving, setSaving] = useState(false)

  // Report type mapping is the single source of truth for prompt selection
  const reportTypes = Array.from(new Set(session.notes.map((n) => n.report_type).filter(Boolean))).sort()
  const currentMapping = session.report_type_mapping || {}
  const [mapping, setMapping] = useState<Record<string, string[]>>(() => {
    const m: Record<string, string[]> = {}
    for (const rt of reportTypes) {
      // Default to current session prompt_types if no mapping exists for this report type
      m[rt] = currentMapping[rt] ? [...currentMapping[rt]] : []
    }
    return m
  })

  const setMappingForRT = (rt: string, pts: string[]) => {
    setMapping((prev) => ({ ...prev, [rt]: pts }))
  }

  const selectAllForRT = (rt: string) => {
    setMappingForRT(rt, [...allPromptTypes])
  }

  const deselectAllForRT = (rt: string) => {
    setMappingForRT(rt, [])
  }

  // Apply the same change across all report types at once
  const selectAllGlobal = () => {
    const m: Record<string, string[]> = {}
    for (const rt of reportTypes) {
      m[rt] = [...allPromptTypes]
    }
    setMapping(m)
  }

  const deselectAllGlobal = () => {
    const m: Record<string, string[]> = {}
    for (const rt of reportTypes) {
      m[rt] = []
    }
    setMapping(m)
  }

  // Derive the effective prompt types from the mapping union
  const effectivePromptTypes = new Set<string>()
  for (const pts of Object.values(mapping)) {
    pts.forEach((pt) => effectivePromptTypes.add(pt))
  }

  const handleSave = async () => {
    setSaving(true)
    try {
      await onSave(mapping)
    } finally {
      setSaving(false)
    }
  }

  const hasChanges = (() => {
    for (const rt of reportTypes) {
      const prev = (currentMapping[rt] || []).slice().sort()
      const next = (mapping[rt] || []).slice().sort()
      if (prev.length !== next.length || prev.some((v, i) => v !== next[i])) return true
    }
    return false
  })()

  // Check which prompt types will be removed (have annotations that will be deleted)
  const removedTypes = session.prompt_types.filter((pt) => !effectivePromptTypes.has(pt))
  const removedWithAnnotations = removedTypes.filter((pt) =>
    Object.values(session.annotations).some((noteAnns) => pt in noteAnns)
  )

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg shadow-xl max-w-3xl w-full mx-4 max-h-[85vh] flex flex-col">
        <div className="p-6 border-b border-gray-200 flex justify-between items-center flex-shrink-0">
          <h2 className="text-xl font-bold text-gray-900">Manage Report Type → Prompt Mapping</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl">
            ✕
          </button>
        </div>

        <div className="p-6 overflow-y-auto flex-1">
          <p className="text-xs text-gray-500 mb-3">
            Select which prompt types apply to each report type. The session&apos;s prompt types are determined by the union of all selections below.
          </p>

          {/* Global controls */}
          <div className="flex items-center justify-between mb-4">
            <span className="text-sm text-gray-700">
              <strong>{effectivePromptTypes.size}</strong> prompt type{effectivePromptTypes.size !== 1 ? 's' : ''} active across {reportTypes.length} report type{reportTypes.length !== 1 ? 's' : ''}
            </span>
            <div className="flex gap-2">
              <button onClick={selectAllGlobal} className="text-xs text-blue-600 hover:text-blue-800 font-medium">Select All Everywhere</button>
              <button onClick={deselectAllGlobal} className="text-xs text-gray-500 hover:text-gray-700 font-medium">Clear All</button>
            </div>
          </div>

          {/* Preset Selector */}
          {reportTypes.length > 0 && (
            <div className="mb-4">
              <PresetSelector
                center={center}
                currentMapping={mapping}
                onLoadPreset={(presetMapping) => {
                  setMapping((prev) => {
                    const updated = { ...prev }
                    for (const rt of reportTypes) {
                      if (presetMapping[rt]) {
                        updated[rt] = presetMapping[rt]
                      }
                    }
                    return updated
                  })
                }}
                reportTypes={reportTypes}
              />
            </div>
          )}

          {reportTypes.length > 0 ? (
            <div className="space-y-4">
              {reportTypes.map((rt) => {
                const selectedForRT = mapping[rt] || []
                return (
                  <div key={rt} className="border border-gray-200 rounded p-3">
                    <div className="flex items-center justify-between mb-2">
                      <h4 className="text-sm font-medium text-gray-800">{rt}</h4>
                      <div className="flex gap-2 items-center">
                        <span className="text-xs text-gray-500">{selectedForRT.length} selected</span>
                        <button onClick={() => selectAllForRT(rt)} className="text-xs text-blue-600 hover:text-blue-800">All</button>
                        <button onClick={() => deselectAllForRT(rt)} className="text-xs text-gray-500 hover:text-gray-700">None</button>
                      </div>
                    </div>
                    <div className="flex flex-wrap gap-1.5">
                      {allPromptTypes.map((pt) => {
                        const isOn = selectedForRT.includes(pt)
                        return (
                          <button
                            key={pt}
                            onClick={() => {
                              if (isOn) {
                                setMappingForRT(rt, selectedForRT.filter((x) => x !== pt))
                              } else {
                                setMappingForRT(rt, [...selectedForRT, pt])
                              }
                            }}
                            className={`text-xs px-2 py-1 rounded-full border transition-colors ${
                              isOn
                                ? 'bg-blue-100 border-blue-300 text-blue-800'
                                : 'bg-gray-50 border-gray-200 text-gray-500 hover:border-gray-300'
                            }`}
                          >
                            {pt}
                          </button>
                        )
                      })}
                    </div>
                  </div>
                )
              })}
            </div>
          ) : (
            <div className="text-sm text-gray-500 border border-gray-200 rounded p-4 text-center">
              No report types found in this session&apos;s notes.
            </div>
          )}

          {/* Warning about annotation deletion */}
          {removedWithAnnotations.length > 0 && (
            <div className="mt-4 p-3 bg-amber-50 border border-amber-200 text-amber-800 rounded text-sm">
              Saving will remove <strong>{removedWithAnnotations.length}</strong> prompt type{removedWithAnnotations.length !== 1 ? 's' : ''} that have existing annotations: {removedWithAnnotations.join(', ')}. Their annotations will be deleted.
            </div>
          )}

          {error && (
            <div className="mt-4 p-3 bg-red-50 border border-red-200 text-red-700 rounded text-sm">
              {error}
            </div>
          )}
        </div>

        {/* Footer with Save */}
        <div className="p-4 border-t border-gray-200 flex justify-end gap-3 flex-shrink-0">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm border border-gray-300 rounded-md text-gray-700 hover:bg-gray-50"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={!hasChanges || saving}
            className="px-4 py-2 text-sm bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {saving ? 'Saving...' : 'Save Changes'}
          </button>
        </div>
      </div>
    </div>
  )
}
