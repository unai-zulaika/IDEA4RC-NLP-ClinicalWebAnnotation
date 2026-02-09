'use client'

import { useState, useEffect } from 'react'
import type { EntityMapping, EntityFieldMapping } from '@/lib/api'

function ValueCodeMappingsSection({
  mappings,
  onChange,
}: {
  mappings?: Record<string, string>
  onChange: (mappings: Record<string, string> | undefined) => void
}) {
  const [expanded, setExpanded] = useState(false)

  const entries = Object.entries(mappings || {})

  const addPair = () => {
    const updated: Record<string, string> = { ...(mappings || {}), '': '' }
    // If there's already an empty key, generate a placeholder key
    if ('' in (mappings || {})) {
      const key = `value_${entries.length + 1}`
      updated[key] = ''
    }
    onChange(updated)
    setExpanded(true)
  }

  const removePair = (key: string) => {
    const updated = { ...(mappings || {}) }
    delete updated[key]
    onChange(Object.keys(updated).length > 0 ? updated : undefined)
  }

  const updateKey = (oldKey: string, newKey: string) => {
    const updated: Record<string, string> = {}
    for (const [k, v] of Object.entries(mappings || {})) {
      if (k === oldKey) {
        updated[newKey] = v
      } else {
        updated[k] = v
      }
    }
    onChange(Object.keys(updated).length > 0 ? updated : undefined)
  }

  const updateValue = (key: string, newValue: string) => {
    const updated = { ...(mappings || {}), [key]: newValue }
    onChange(updated)
  }

  return (
    <div className="mt-2 border border-gray-200 rounded-md">
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className="w-full flex justify-between items-center px-2 py-1.5 text-xs font-medium text-gray-700 bg-gray-100 hover:bg-gray-200 rounded-t-md"
      >
        <span>Value-to-Code Mappings {entries.length > 0 && `(${entries.length})`}</span>
        <span>{expanded ? '\u25B2' : '\u25BC'}</span>
      </button>
      {expanded && (
        <div className="p-2 space-y-1.5">
          <p className="text-xs text-gray-500">
            Map extracted values to IDEA4RC code IDs. When a match is found, the code is used directly during export.
          </p>
          {entries.map(([key, val], i) => (
            <div key={i} className="flex items-center gap-1.5">
              <input
                type="text"
                value={key}
                onChange={(e) => updateKey(key, e.target.value)}
                placeholder="Value (e.g. 1)"
                className="flex-1 px-2 py-1 border border-gray-300 rounded text-xs"
              />
              <span className="text-xs text-gray-400">{'\u2192'}</span>
              <input
                type="text"
                value={val}
                onChange={(e) => updateValue(key, e.target.value)}
                placeholder="Code (e.g. 1634371)"
                className="flex-1 px-2 py-1 border border-gray-300 rounded text-xs"
              />
              <button
                type="button"
                onClick={() => removePair(key)}
                className="px-1.5 py-0.5 bg-red-500 text-white rounded text-xs hover:bg-red-600"
                title="Remove mapping"
              >
                x
              </button>
            </div>
          ))}
          <button
            type="button"
            onClick={addPair}
            className="text-xs text-green-700 hover:text-green-900 font-medium"
          >
            + Add Value Mapping
          </button>
        </div>
      )}
    </div>
  )
}

interface EntityMappingEditorProps {
  mapping: EntityMapping | null
  template: string
  onChange: (mapping: EntityMapping | null) => void
}

export default function EntityMappingEditor({ mapping, template, onChange }: EntityMappingEditorProps) {
  const [entityType, setEntityType] = useState(mapping?.entity_type || '')
  const [factTrigger, setFactTrigger] = useState(mapping?.fact_trigger || '')
  const [fieldMappings, setFieldMappings] = useState<EntityFieldMapping[]>(
    mapping?.field_mappings || []
  )
  const [saveStatus, setSaveStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle')

  // Sync state when mapping prop changes
  useEffect(() => {
    setEntityType(mapping?.entity_type || '')
    setFactTrigger(mapping?.fact_trigger || '')
    setFieldMappings(mapping?.field_mappings || [])
    setSaveStatus('idle')
  }, [mapping])

  // Extract placeholders from template (e.g., [select intention], [put date])
  const extractPlaceholders = (text: string): string[] => {
    const placeholderRegex = /\[([^\]]+)\]/g
    const matches = text.matchAll(placeholderRegex)
    const placeholders = Array.from(matches, (match) => `[${match[1]}]`)
    return Array.from(new Set(placeholders)) // Remove duplicates
  }

  const placeholders = extractPlaceholders(template)

  const handleSave = async () => {
    if (!entityType.trim()) {
      alert('Entity type is required')
      return
    }

    setSaveStatus('saving')

    try {
      const newMapping: EntityMapping = {
        entity_type: entityType.trim(),
        fact_trigger: factTrigger.trim() || undefined,
        field_mappings: fieldMappings.filter(fm => 
          fm.template_placeholder && fm.entity_type && fm.field_name
        )
      }

      onChange(newMapping)
      setSaveStatus('saved')
      setTimeout(() => setSaveStatus('idle'), 2000)
    } catch (error) {
      setSaveStatus('error')
      setTimeout(() => setSaveStatus('idle'), 3000)
    }
  }

  const handleClear = () => {
    setEntityType('')
    setFactTrigger('')
    setFieldMappings([])
    onChange(null)
  }

  const addFieldMapping = () => {
    setFieldMappings([...fieldMappings, {
      template_placeholder: '',
      entity_type: entityType || '',
      field_name: ''
    }])
  }

  const updateFieldMapping = (index: number, field: Partial<EntityFieldMapping>) => {
    const updated = [...fieldMappings]
    updated[index] = { ...updated[index], ...field }
    setFieldMappings(updated)
  }

  const removeFieldMapping = (index: number) => {
    setFieldMappings(fieldMappings.filter((_, i) => i !== index))
  }

  const hasMapping = entityType || fieldMappings.length > 0

  return (
    <div className="bg-white border border-gray-300 rounded-lg p-4 space-y-4">
      <div className="flex justify-between items-center">
        {/* <h3 className="text-lg font-semibold text-gray-900">Entity Mapping</h3> */}
        <div className="flex gap-2 items-center">
          {hasMapping && (
            <>
              <button
                onClick={handleSave}
                disabled={saveStatus === 'saving'}
                className="px-3 py-1 bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:opacity-50 text-sm"
              >
                {saveStatus === 'saving' ? 'Saving...' : saveStatus === 'saved' ? '✓ Saved' : 'Save Mapping'}
              </button>
              {saveStatus === 'saved' && (
                <span className="text-sm text-green-600">Mapping saved!</span>
              )}
              {saveStatus === 'error' && (
                <span className="text-sm text-red-600">Error saving mapping</span>
              )}
            </>
          )}
          {hasMapping && (
            <button
              onClick={handleClear}
              className="px-3 py-1 bg-gray-300 text-gray-700 rounded-md hover:bg-gray-400 text-sm"
            >
              Clear
            </button>
          )}
        </div>
      </div>

      {!hasMapping && (
        <div className="bg-blue-50 border border-blue-200 rounded-md p-3">
          <p className="text-sm text-blue-800 font-semibold mb-2">How Entity Mapping Works:</p>
          <p className="text-xs text-blue-700 mb-2">
            Entity mappings connect annotation template values to structured entity fields. There are two types:
          </p>
          <div className="space-y-2 text-xs text-blue-700">
            <div>
              <strong>1. Main Fact (Entity Type):</strong> Maps to the fact that something happened
              <ul className="ml-4 mt-1 list-disc">
                <li>Example: "Radiotherapy" entity is created when annotation mentions radiotherapy</li>
                <li>Fact Trigger: "pre-operative radiotherapy" (optional pattern to identify the fact)</li>
              </ul>
            </div>
            <div>
              <strong>2. Field Mappings:</strong> Maps placeholder values in brackets to entity fields
              <ul className="ml-4 mt-1 list-disc">
                <li>[select intention] → Radiotherapy.intent</li>
                <li>[please select where] → Radiotherapy.site</li>
                <li>[put date] → Radiotherapy.date</li>
              </ul>
            </div>
          </div>
          <p className="text-xs text-blue-600 mt-2 italic">
            Example annotation: "pre-operative radiotherapy (conventional) with [select intention] intention started [please select where] on [put date]"
          </p>
        </div>
      )}

      <div className="space-y-3">
        {/* Entity Type - Maps to the main fact */}
        <div className="bg-blue-50 border border-blue-200 rounded-md p-3">
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Entity Type (Main Fact) <span className="text-red-500">*</span>
          </label>
          <input
            type="text"
            value={entityType}
            onChange={(e) => setEntityType(e.target.value)}
            placeholder="e.g., Radiotherapy"
            className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          <p className="text-xs text-gray-600 mt-1">
            <strong>Maps to:</strong> The fact that this entity/event occurred (e.g., "Radiotherapy happened")
          </p>
        </div>

        {/* Fact Trigger (Optional) */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Fact Trigger Pattern (Optional)
          </label>
          <input
            type="text"
            value={factTrigger}
            onChange={(e) => setFactTrigger(e.target.value)}
            placeholder="e.g., pre-operative radiotherapy"
            className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          <p className="text-xs text-gray-500 mt-1">
            Text pattern in the annotation that indicates this fact occurred (helps identify when to create the entity)
          </p>
        </div>

        {/* Field Mappings - Maps to individual placeholder values */}
        <div>
          <div className="flex justify-between items-center mb-2">
            <div>
              <label className="block text-sm font-medium text-gray-700">
                Field Mappings (Placeholder Values)
              </label>
              <p className="text-xs text-gray-500">
                Map individual placeholder values in brackets to entity fields
              </p>
            </div>
            <button
              onClick={addFieldMapping}
              className="px-2 py-1 bg-green-600 text-white rounded-md hover:bg-green-700 text-xs"
            >
              + Add Mapping
            </button>
          </div>

          {fieldMappings.length === 0 ? (
            <p className="text-sm text-gray-500 italic">No field mappings defined</p>
          ) : (
            <div className="space-y-2">
              {fieldMappings.map((fm, index) => (
                <div key={index} className="border border-gray-200 rounded-md p-3 bg-gray-50">
                  <div className="grid grid-cols-3 gap-2">
                    <div>
                      <label className="block text-xs font-medium text-gray-600 mb-1">
                        Template Placeholder
                      </label>
                      <select
                        value={fm.template_placeholder}
                        onChange={(e) => updateFieldMapping(index, { template_placeholder: e.target.value })}
                        className="w-full px-2 py-1 border border-gray-300 rounded-md text-sm"
                      >
                        <option value="">Select placeholder or fact...</option>
                        <option value="[FULL_ANNOTATION]">[FULL_ANNOTATION] - The entire annotation text</option>
                        {placeholders.map((ph) => (
                          <option key={ph} value={ph}>
                            {ph}
                          </option>
                        ))}
                      </select>
                    </div>
                    <div>
                      <label className="block text-xs font-medium text-gray-600 mb-1">
                        Entity Type
                      </label>
                      <input
                        type="text"
                        value={fm.entity_type}
                        onChange={(e) => updateFieldMapping(index, { entity_type: e.target.value })}
                        placeholder="e.g., Radiotherapy"
                        className="w-full px-2 py-1 border border-gray-300 rounded-md text-sm"
                      />
                    </div>
                    <div className="flex gap-2">
                      <div className="flex-1">
                        <label className="block text-xs font-medium text-gray-600 mb-1">
                          Field Name
                        </label>
                        <input
                          type="text"
                          value={fm.field_name}
                          onChange={(e) => updateFieldMapping(index, { field_name: e.target.value })}
                          placeholder="e.g., intent"
                          className="w-full px-2 py-1 border border-gray-300 rounded-md text-sm"
                        />
                      </div>
                      <button
                        onClick={() => removeFieldMapping(index)}
                        className="px-2 py-1 bg-red-500 text-white rounded-md hover:bg-red-600 text-xs mt-5"
                        title="Remove mapping"
                      >
                        ×
                      </button>
                    </div>
                  </div>
                  <div className="mt-2">
                    <label className="block text-xs font-medium text-gray-600 mb-1">
                      Hardcoded value (optional)
                    </label>
                    <input
                      type="text"
                      value={fm.hardcoded_value ?? ''}
                      onChange={(e) => updateFieldMapping(index, { hardcoded_value: e.target.value || undefined })}
                      placeholder="Fixed value for this field (overrides extraction)"
                      className="w-full px-2 py-1 border border-gray-300 rounded-md text-sm"
                    />
                    <p className="text-xs text-gray-500 mt-0.5">
                      If set, this value is used for the field instead of extracting from the annotation.
                    </p>
                  </div>
                  {/* Value-to-Code Mappings */}
                  <ValueCodeMappingsSection
                    mappings={fm.value_code_mappings}
                    onChange={(vcm) => updateFieldMapping(index, { value_code_mappings: vcm })}
                  />
                </div>
              ))}
            </div>
          )}

          <div className="mt-2 p-2 bg-blue-50 rounded-md">
            <p className="text-xs font-medium text-blue-900 mb-1">Available options for mapping:</p>
            <div className="space-y-1">
              <div className="flex items-center gap-2">
                <span className="text-xs bg-blue-100 text-blue-800 px-2 py-1 rounded font-mono">
                  [FULL_ANNOTATION]
                </span>
                <span className="text-xs text-blue-700">- Map the entire annotation text</span>
              </div>
              {placeholders.length > 0 && (
                <div className="flex flex-wrap gap-1">
                  {placeholders.map((ph) => (
                    <span key={ph} className="text-xs bg-blue-100 text-blue-800 px-2 py-1 rounded font-mono">
                      {ph}
                    </span>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

