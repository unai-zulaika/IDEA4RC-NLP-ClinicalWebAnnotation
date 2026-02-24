'use client'

import { useState, useEffect } from 'react'
import { presetsApi, promptsApi } from '@/lib/api'
import type { AnnotationPreset, PromptInfo } from '@/lib/api'
import { useDefaultCenter } from '@/lib/useDefaultCenter'

export default function PresetsPage() {
  const [selectedCenter, setSelectedCenter] = useDefaultCenter()
  const [centers, setCenters] = useState<string[]>([])
  const [presets, setPresets] = useState<AnnotationPreset[]>([])
  const [prompts, setPrompts] = useState<PromptInfo[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Create/Edit form state
  const [showForm, setShowForm] = useState(false)
  const [editingPreset, setEditingPreset] = useState<AnnotationPreset | null>(null)
  const [formName, setFormName] = useState('')
  const [formDescription, setFormDescription] = useState('')
  const [formMapping, setFormMapping] = useState<Record<string, string[]>>({})
  const [reportTypeInput, setReportTypeInput] = useState('')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    promptsApi.listCenters().then(setCenters).catch(console.error)
  }, [])

  useEffect(() => {
    if (centers.length > 0 && !centers.includes(selectedCenter)) {
      setSelectedCenter(centers[0])
    }
  }, [centers, selectedCenter, setSelectedCenter])

  const [refreshKey, setRefreshKey] = useState(0)

  useEffect(() => {
    if (!selectedCenter) return
    let cancelled = false
    const load = async () => {
      setLoading(true)
      try {
        const [presetsData, promptsData] = await Promise.all([
          presetsApi.list(selectedCenter),
          promptsApi.list(selectedCenter),
        ])
        if (!cancelled) {
          setPresets(presetsData)
          setPrompts(promptsData)
        }
      } catch (err) {
        if (!cancelled) console.error('Failed to load data:', err)
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => { cancelled = true }
  }, [selectedCenter, refreshKey])

  const loadData = () => setRefreshKey((k) => k + 1)

  const resetForm = () => {
    setFormName('')
    setFormDescription('')
    setFormMapping({})
    setReportTypeInput('')
    setEditingPreset(null)
    setShowForm(false)
    setError(null)
  }

  const startCreate = () => {
    resetForm()
    setShowForm(true)
  }

  const startEdit = (preset: AnnotationPreset) => {
    setEditingPreset(preset)
    setFormName(preset.name)
    setFormDescription(preset.description || '')
    setFormMapping({ ...preset.report_type_mapping })
    setReportTypeInput('')
    setShowForm(true)
    setError(null)
  }

  const handleAddReportType = () => {
    const rt = reportTypeInput.trim()
    if (!rt || formMapping[rt]) return
    setFormMapping({ ...formMapping, [rt]: [] })
    setReportTypeInput('')
  }

  const handleRemoveReportType = (rt: string) => {
    const updated = { ...formMapping }
    delete updated[rt]
    setFormMapping(updated)
  }

  const togglePromptForRT = (rt: string, promptType: string) => {
    const current = formMapping[rt] || []
    if (current.includes(promptType)) {
      setFormMapping({ ...formMapping, [rt]: current.filter((p) => p !== promptType) })
    } else {
      setFormMapping({ ...formMapping, [rt]: [...current, promptType] })
    }
  }

  const selectAllForRT = (rt: string) => {
    setFormMapping({ ...formMapping, [rt]: prompts.map((p) => p.prompt_type) })
  }

  const deselectAllForRT = (rt: string) => {
    setFormMapping({ ...formMapping, [rt]: [] })
  }

  const handleSave = async () => {
    if (!formName.trim()) {
      setError('Name is required')
      return
    }
    if (Object.keys(formMapping).length === 0) {
      setError('Add at least one report type')
      return
    }

    setSaving(true)
    setError(null)
    try {
      if (editingPreset) {
        await presetsApi.update(editingPreset.id, {
          name: formName.trim(),
          description: formDescription.trim() || undefined,
          report_type_mapping: formMapping,
        })
      } else {
        await presetsApi.create({
          name: formName.trim(),
          center: selectedCenter,
          description: formDescription.trim() || undefined,
          report_type_mapping: formMapping,
        })
      }
      resetForm()
      await loadData()
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || 'Failed to save preset')
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (preset: AnnotationPreset) => {
    if (!confirm(`Delete preset "${preset.name}"?`)) return
    try {
      await presetsApi.delete(preset.id)
      await loadData()
    } catch (err: any) {
      alert(err.response?.data?.detail || err.message || 'Failed to delete preset')
    }
  }

  const allPromptTypes = prompts.map((p) => p.prompt_type)

  return (
    <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      <div className="flex items-center justify-between mb-8">
        <h1 className="text-3xl font-bold text-gray-900">Annotation Presets</h1>
        <div className="flex items-center gap-4">
          {centers.length > 0 && (
            <div className="flex items-center">
              <label className="text-sm font-medium text-gray-700 mr-2">Center:</label>
              <select
                value={selectedCenter}
                onChange={(e) => setSelectedCenter(e.target.value)}
                className="px-3 py-2 border border-gray-300 rounded-md text-sm"
              >
                {centers.map((c) => (
                  <option key={c} value={c}>{c}</option>
                ))}
              </select>
            </div>
          )}
          {!showForm && (
            <button
              onClick={startCreate}
              className="px-4 py-2 bg-green-600 text-white rounded-md hover:bg-green-700 text-sm font-medium"
            >
              + Create Preset
            </button>
          )}
        </div>
      </div>

      {/* Create/Edit Form */}
      {showForm && (
        <div className="bg-white rounded-lg shadow p-6 mb-6">
          <h2 className="text-lg font-semibold text-gray-900 mb-4">
            {editingPreset ? 'Edit Preset' : 'Create Preset'}
          </h2>

          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Name</label>
              <input
                type="text"
                value={formName}
                onChange={(e) => setFormName(e.target.value)}
                className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm"
                placeholder="e.g. Breast Cancer Standard"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Description (optional)</label>
              <input
                type="text"
                value={formDescription}
                onChange={(e) => setFormDescription(e.target.value)}
                className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm"
                placeholder="Standard mapping for breast cancer reports"
              />
            </div>

            {/* Report type mapping */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">Report Type Mappings</label>
              <div className="flex gap-2 mb-3">
                <input
                  type="text"
                  value={reportTypeInput}
                  onChange={(e) => setReportTypeInput(e.target.value)}
                  onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); handleAddReportType() } }}
                  className="flex-1 px-3 py-2 border border-gray-300 rounded-md text-sm"
                  placeholder="Add report type (e.g. pathology, radiology)"
                />
                <button
                  type="button"
                  onClick={handleAddReportType}
                  disabled={!reportTypeInput.trim()}
                  className="px-3 py-2 bg-blue-600 text-white rounded-md text-sm hover:bg-blue-700 disabled:opacity-50"
                >
                  Add
                </button>
              </div>

              {Object.keys(formMapping).length === 0 ? (
                <div className="text-sm text-gray-500 border border-gray-200 rounded-md p-4 text-center">
                  No report types added yet. Type a report type name above and click Add.
                </div>
              ) : (
                <div className="space-y-4 border border-gray-300 rounded-md p-4">
                  {Object.keys(formMapping).sort().map((rt) => (
                    <div key={rt} className="border-b border-gray-200 last:border-b-0 pb-4 last:pb-0">
                      <div className="flex items-center justify-between mb-2">
                        <h4 className="text-sm font-semibold text-gray-800">{rt}</h4>
                        <div className="flex gap-2 items-center">
                          <span className="text-xs text-gray-500">{(formMapping[rt] || []).length} selected</span>
                          <button type="button" onClick={() => selectAllForRT(rt)} className="text-xs text-blue-600 hover:text-blue-800">All</button>
                          <button type="button" onClick={() => deselectAllForRT(rt)} className="text-xs text-gray-500 hover:text-gray-700">None</button>
                          <button type="button" onClick={() => handleRemoveReportType(rt)} className="text-xs text-red-600 hover:text-red-800">Remove</button>
                        </div>
                      </div>
                      <div className="grid grid-cols-2 md:grid-cols-3 gap-2 max-h-48 overflow-y-auto">
                        {allPromptTypes.map((pt) => (
                          <label key={pt} className="flex items-center space-x-2 py-1 text-sm">
                            <input
                              type="checkbox"
                              checked={(formMapping[rt] || []).includes(pt)}
                              onChange={() => togglePromptForRT(rt, pt)}
                              className="rounded border-gray-300 text-primary-600 focus:ring-primary-500"
                            />
                            <span className="text-gray-700">{pt}</span>
                          </label>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {error && (
              <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded text-sm">
                {error}
              </div>
            )}

            <div className="flex gap-3 justify-end">
              <button
                type="button"
                onClick={resetForm}
                className="px-4 py-2 border border-gray-300 rounded-md text-sm text-gray-700 hover:bg-gray-50"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleSave}
                disabled={saving || !formName.trim()}
                className="px-4 py-2 bg-primary-600 text-white rounded-md hover:bg-primary-700 disabled:opacity-50 disabled:cursor-not-allowed text-sm"
              >
                {saving ? 'Saving...' : editingPreset ? 'Update Preset' : 'Create Preset'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Presets List */}
      {loading ? (
        <div className="text-center text-gray-500 py-8">Loading...</div>
      ) : presets.length === 0 ? (
        <div className="bg-white rounded-lg shadow p-8 text-center text-gray-500">
          No presets found for center "{selectedCenter}". Create one to get started.
        </div>
      ) : (
        <div className="space-y-4">
          {presets.map((preset) => {
            const rtCount = Object.keys(preset.report_type_mapping).length
            const ptCount = new Set(Object.values(preset.report_type_mapping).flat()).size
            return (
              <div key={preset.id} className="bg-white rounded-lg shadow p-5">
                <div className="flex items-start justify-between">
                  <div className="flex-1">
                    <h3 className="text-lg font-semibold text-gray-900">{preset.name}</h3>
                    {preset.description && (
                      <p className="text-sm text-gray-600 mt-1">{preset.description}</p>
                    )}
                    <div className="flex gap-4 mt-2 text-xs text-gray-500">
                      <span>{rtCount} report type{rtCount !== 1 ? 's' : ''}</span>
                      <span>{ptCount} prompt type{ptCount !== 1 ? 's' : ''}</span>
                      <span>Updated {new Date(preset.updated_at).toLocaleDateString()}</span>
                    </div>
                    {/* Show mapping summary */}
                    <div className="mt-3 space-y-1">
                      {Object.entries(preset.report_type_mapping).map(([rt, pts]) => (
                        <div key={rt} className="text-xs text-gray-600">
                          <span className="font-medium">{rt}:</span>{' '}
                          {pts.length > 3
                            ? `${pts.slice(0, 3).join(', ')} +${pts.length - 3} more`
                            : pts.join(', ')}
                        </div>
                      ))}
                    </div>
                  </div>
                  <div className="flex gap-2 ml-4">
                    <button
                      onClick={() => startEdit(preset)}
                      className="px-3 py-1.5 border border-gray-300 rounded-md text-sm text-gray-700 hover:bg-gray-50"
                    >
                      Edit
                    </button>
                    <button
                      onClick={() => handleDelete(preset)}
                      className="px-3 py-1.5 border border-red-300 rounded-md text-sm text-red-700 hover:bg-red-50"
                    >
                      Delete
                    </button>
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
