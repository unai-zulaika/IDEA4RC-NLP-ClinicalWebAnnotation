'use client'

import { useState, useEffect } from 'react'
import Editor from '@monaco-editor/react'
import { promptsApi } from '@/lib/api'
import type { PromptInfo, EntityMapping } from '@/lib/api'
import EntityMappingEditor from './EntityMappingEditor'

interface PromptEditorProps {
  promptType: string
  center?: string
  onSave?: () => void
  onDelete?: () => void
}

export default function PromptEditor({ promptType, center = 'INT', onSave, onDelete }: PromptEditorProps) {
  const [prompt, setPrompt] = useState<PromptInfo | null>(null)
  const [template, setTemplate] = useState('')
  const [promptName, setPromptName] = useState('')
  const [isRenaming, setIsRenaming] = useState(false)
  const [saving, setSaving] = useState(false)
  const [renaming, setRenaming] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState(false)
  const [entityMapping, setEntityMapping] = useState<EntityMapping | null>(null)
  const [showMappingEditor, setShowMappingEditor] = useState(false)

  useEffect(() => {
    loadPrompt()
  }, [promptType, center])

  const loadPrompt = async () => {
    try {
      const data = await promptsApi.get(promptType, center)
      setPrompt(data)
      setTemplate(data.template)
      setPromptName(data.prompt_type)
      setEntityMapping(data.entity_mapping || null)
      setIsRenaming(false)
    } catch (err: any) {
      setError(err.message || 'Failed to load prompt')
    }
  }

  const handleSave = async () => {
    setSaving(true)
    setError(null)
    setSuccess(false)

    try {
      await promptsApi.update(promptType, template, entityMapping || undefined, center)
      setSuccess(true)
      setTimeout(() => setSuccess(false), 3000)
      onSave?.()
    } catch (err: any) {
      setError(err.message || 'Failed to save prompt')
    } finally {
      setSaving(false)
    }
  }

  const handleRename = async () => {
    if (!promptName || promptName === promptType) {
      setIsRenaming(false)
      setPromptName(promptType)
      return
    }

    setRenaming(true)
    setError(null)
    setSuccess(false)

    try {
      await promptsApi.rename(promptType, promptName, center)
      setSuccess(true)
      setTimeout(() => setSuccess(false), 3000)
      setIsRenaming(false)
      onSave?.() // Reload prompts list
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || 'Failed to rename prompt')
      setPromptName(promptType) // Reset on error
    } finally {
      setRenaming(false)
    }
  }

  const handleDelete = async () => {
    if (!confirmDelete) {
      setConfirmDelete(true)
      return
    }
    setDeleting(true)
    setError(null)
    try {
      await promptsApi.delete(promptType, center)
      setConfirmDelete(false)
      onDelete?.()
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || 'Failed to delete prompt')
    } finally {
      setDeleting(false)
    }
  }

  const handleCancelRename = () => {
    setIsRenaming(false)
    setPromptName(promptType)
  }

  if (!prompt) {
    return <div className="text-gray-500">Loading prompt...</div>
  }

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <div className="flex items-center gap-2 flex-1">
          {isRenaming ? (
            <div className="flex items-center gap-2 flex-1">
              <input
                type="text"
                value={promptName}
                onChange={(e) => setPromptName(e.target.value)}
                className="px-3 py-1 border border-gray-300 rounded-md text-lg font-semibold flex-1"
                placeholder="Enter new prompt name"
                autoFocus
              />
              <button
                onClick={handleRename}
                disabled={renaming || !promptName || promptName === promptType}
                className="px-3 py-1 bg-green-600 text-white rounded-md hover:bg-green-700 disabled:opacity-50 text-sm"
              >
                {renaming ? 'Renaming...' : 'Save'}
              </button>
              <button
                onClick={handleCancelRename}
                disabled={renaming}
                className="px-3 py-1 bg-gray-300 text-gray-700 rounded-md hover:bg-gray-400 disabled:opacity-50 text-sm"
              >
                Cancel
              </button>
            </div>
          ) : (
            <div className="flex items-center gap-2 flex-1">
              <h3 className="text-lg font-semibold text-gray-900">
                {promptType}
              </h3>
              <button
                onClick={() => setIsRenaming(true)}
                className="text-sm text-gray-500 hover:text-gray-700 px-2 py-1"
                title="Rename prompt"
              >
                ✏️
              </button>
            </div>
          )}
        </div>
        {!isRenaming && (
          <div className="flex items-center gap-2">
            <button
              onClick={handleSave}
              disabled={saving}
              className="px-4 py-2 bg-primary-600 text-white rounded-md hover:bg-primary-700 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {saving ? 'Saving...' : 'Save'}
            </button>
            {onDelete && (
              <span className="flex items-center gap-1">
                {confirmDelete && (
                  <button
                    type="button"
                    onClick={() => setConfirmDelete(false)}
                    className="px-3 py-2 text-gray-600 hover:text-gray-800 text-sm"
                  >
                    Cancel
                  </button>
                )}
                <button
                  onClick={handleDelete}
                  disabled={deleting}
                  className={`px-4 py-2 rounded-md text-sm font-medium ${
                    confirmDelete
                      ? 'bg-red-600 text-white hover:bg-red-700'
                      : 'bg-gray-200 text-gray-700 hover:bg-gray-300'
                  } disabled:opacity-50 disabled:cursor-not-allowed`}
                  title={confirmDelete ? 'Click again to confirm delete' : 'Delete this prompt'}
                >
                  {deleting ? 'Deleting...' : confirmDelete ? 'Confirm delete?' : 'Delete'}
                </button>
              </span>
            )}
          </div>
        )}
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded">
          {error}
        </div>
      )}

      {success && (
        <div className="bg-green-50 border border-green-200 text-green-700 px-4 py-3 rounded">
          Prompt saved successfully!
        </div>
      )}

      {/* Entity Mapping Section */}
      <div className="border border-gray-300 rounded-lg p-4">
        <div className="flex justify-between items-center mb-2">
          <h3 className="text-md font-semibold text-gray-900">Entity Mapping</h3>
          <button
            onClick={() => setShowMappingEditor(!showMappingEditor)}
            className="px-3 py-1 bg-gray-200 text-gray-700 rounded-md hover:bg-gray-300 text-sm"
          >
            {showMappingEditor ? 'Hide' : 'Show'} Mapping Editor
          </button>
        </div>
        {entityMapping && !showMappingEditor && (
          <div className="text-sm text-gray-600">
            <p><strong>Entity Type:</strong> {entityMapping.entity_type}</p>
            {entityMapping.fact_trigger && (
              <p><strong>Fact Trigger:</strong> {entityMapping.fact_trigger}</p>
            )}
            <p><strong>Field Mappings:</strong> {entityMapping.field_mappings.length}</p>
          </div>
        )}
        {showMappingEditor && (
          <EntityMappingEditor
            mapping={entityMapping}
            template={template}
            onChange={async (mapping) => {
              setEntityMapping(mapping)
              // Save mapping immediately when changed
              try {
                await promptsApi.update(promptType, template, mapping || undefined, center)
                // Show success feedback
                setSuccess(true)
                setTimeout(() => setSuccess(false), 2000)
              } catch (err: any) {
                setError(err.message || 'Failed to save mapping')
                console.error('Failed to save mapping:', err)
              }
            }}
          />
        )}
      </div>

      <div className="border border-gray-300 rounded-lg overflow-hidden">
        <Editor
          height="600px"
          defaultLanguage="plaintext"
          value={template}
          onChange={(value) => setTemplate(value || '')}
          options={{
            minimap: { enabled: true },
            fontSize: 14,
            wordWrap: 'on',
            lineNumbers: 'on',
          }}
        />
      </div>
    </div>
  )
}

