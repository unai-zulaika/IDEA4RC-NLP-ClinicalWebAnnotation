'use client'

import { useState, useEffect } from 'react'
import { presetsApi } from '@/lib/api'
import type { AnnotationPreset } from '@/lib/api'

interface PresetSelectorProps {
  center: string
  currentMapping: Record<string, string[]>
  onLoadPreset: (mapping: Record<string, string[]>) => void
  reportTypes?: string[]
}

export default function PresetSelector({
  center,
  currentMapping,
  onLoadPreset,
  reportTypes,
}: PresetSelectorProps) {
  const [presets, setPresets] = useState<AnnotationPreset[]>([])
  const [selectedPresetId, setSelectedPresetId] = useState('')
  const [showSaveForm, setShowSaveForm] = useState(false)
  const [saveName, setSaveName] = useState('')
  const [saveDescription, setSaveDescription] = useState('')
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState<string | null>(null)

  const loadPresets = async () => {
    try {
      const data = await presetsApi.list(center)
      setPresets(data)
    } catch (err) {
      console.error('Failed to load presets:', err)
    }
  }

  useEffect(() => {
    if (center) loadPresets()
  }, [center])

  const handleLoad = () => {
    const preset = presets.find((p) => p.id === selectedPresetId)
    if (!preset) return

    let mapping = preset.report_type_mapping
    if (reportTypes) {
      const filtered: Record<string, string[]> = {}
      for (const rt of reportTypes) {
        if (mapping[rt]) {
          filtered[rt] = mapping[rt]
        }
      }
      mapping = filtered
    }
    onLoadPreset(mapping)
    setMessage(`Loaded preset "${preset.name}"`)
    setTimeout(() => setMessage(null), 3000)
  }

  const handleSave = async () => {
    if (!saveName.trim()) return
    setSaving(true)
    try {
      await presetsApi.create({
        name: saveName.trim(),
        center,
        description: saveDescription.trim() || undefined,
        report_type_mapping: currentMapping,
      })
      setSaveName('')
      setSaveDescription('')
      setShowSaveForm(false)
      await loadPresets()
      setMessage('Preset saved successfully')
      setTimeout(() => setMessage(null), 3000)
    } catch (err: any) {
      alert(err.response?.data?.detail || err.message || 'Failed to save preset')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="border border-gray-200 rounded-md p-3 bg-gray-50">
      <div className="flex items-center justify-between mb-2">
        <span className="text-sm font-medium text-gray-700">Annotation Presets</span>
        <button
          type="button"
          onClick={() => setShowSaveForm(!showSaveForm)}
          className="text-xs text-blue-600 hover:text-blue-800 font-medium"
        >
          {showSaveForm ? 'Cancel' : 'Save as Preset'}
        </button>
      </div>

      {/* Load preset */}
      <div className="flex gap-2 mb-2">
        <select
          value={selectedPresetId}
          onChange={(e) => setSelectedPresetId(e.target.value)}
          className="flex-1 px-3 py-2 border border-gray-300 rounded-md text-sm"
        >
          <option value="">Select a preset...</option>
          {presets.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name} ({Object.keys(p.report_type_mapping).length} report types)
            </option>
          ))}
        </select>
        <button
          type="button"
          onClick={handleLoad}
          disabled={!selectedPresetId}
          className="px-3 py-2 bg-blue-600 text-white rounded-md text-sm hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          Load
        </button>
      </div>

      {/* Save form */}
      {showSaveForm && (
        <div className="border-t border-gray-200 pt-2 mt-2 space-y-2">
          <input
            type="text"
            placeholder="Preset name"
            value={saveName}
            onChange={(e) => setSaveName(e.target.value)}
            className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm"
          />
          <input
            type="text"
            placeholder="Description (optional)"
            value={saveDescription}
            onChange={(e) => setSaveDescription(e.target.value)}
            className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm"
          />
          <button
            type="button"
            onClick={handleSave}
            disabled={saving || !saveName.trim()}
            className="w-full px-3 py-2 bg-green-600 text-white rounded-md text-sm hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {saving ? 'Saving...' : 'Save Preset'}
          </button>
        </div>
      )}

      {/* Feedback message */}
      {message && (
        <div className="mt-2 text-xs text-green-700 bg-green-50 border border-green-200 rounded px-2 py-1">
          {message}
        </div>
      )}
    </div>
  )
}
