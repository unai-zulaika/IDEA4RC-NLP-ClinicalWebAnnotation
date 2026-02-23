'use client'

import { useState, useEffect } from 'react'
import { promptsApi } from '@/lib/api'
import type { PromptInfo } from '@/lib/api'
import PromptEditor from '@/components/PromptEditor'
import { useDefaultCenter } from '@/lib/useDefaultCenter'

export default function PromptsPage() {
  const [centers, setCenters] = useState<string[]>([])
  const [selectedCenter, setSelectedCenter] = useDefaultCenter()
  const [prompts, setPrompts] = useState<PromptInfo[]>([])
  const [selectedPrompt, setSelectedPrompt] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [searchQuery, setSearchQuery] = useState('')
  const [showCreateForm, setShowCreateForm] = useState(false)
  const [newPromptName, setNewPromptName] = useState('')
  const [newPromptTemplate, setNewPromptTemplate] = useState(`You are a medical expert. Your task is to extract information from clinical notes.

{few_shot_examples}

Medical Note:
{{note_original_text}}

Annotation:`)
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [showNewCenterForm, setShowNewCenterForm] = useState(false)
  const [newCenterName, setNewCenterName] = useState('')
  const [creatingCenter, setCreatingCenter] = useState(false)
  const [centerError, setCenterError] = useState<string | null>(null)

  const loadCenters = async () => {
    try {
      const data = await promptsApi.listCenters()
      setCenters(data)
      if (data.length > 0 && !data.includes(selectedCenter)) {
        setSelectedCenter(data[0])
      }
    } catch (e) {
      console.error('Failed to load centers:', e)
    }
  }

  useEffect(() => {
    loadCenters()
  }, [])

  useEffect(() => {
    if (selectedCenter) {
      setSelectedPrompt(null)
      loadPrompts()
    }
  }, [selectedCenter])

  const loadPrompts = async () => {
    if (!selectedCenter) return
    setLoading(true)
    try {
      const data = await promptsApi.list(selectedCenter)
      setPrompts(data)
      if (selectedPrompt && data.some((p) => p.prompt_type === selectedPrompt)) {
        // Keep current selection
      } else if (data.length > 0) {
        setSelectedPrompt(data[0].prompt_type)
      } else {
        setSelectedPrompt(null)
      }
    } catch (error) {
      console.error('Failed to load prompts:', error)
    } finally {
      setLoading(false)
    }
  }

  const handleCreatePrompt = async () => {
    if (!newPromptName.trim()) {
      setError('Prompt name cannot be empty')
      return
    }
    if (!newPromptTemplate.trim()) {
      setError('Prompt template cannot be empty')
      return
    }

    setCreating(true)
    setError(null)

    try {
      const newPrompt = await promptsApi.create(newPromptName.trim(), newPromptTemplate.trim(), selectedCenter)
      await loadPrompts()
      setSelectedPrompt(newPrompt.prompt_type)
      setShowCreateForm(false)
      setNewPromptName('')
      setNewPromptTemplate('')
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || 'Failed to create prompt')
    } finally {
      setCreating(false)
    }
  }

  const handleCreateCenter = async () => {
    const name = newCenterName.trim()
    if (!name) {
      setCenterError('Center name cannot be empty')
      return
    }

    setCreatingCenter(true)
    setCenterError(null)
    try {
      await promptsApi.createCenter(name)
      await loadCenters()
      setSelectedCenter(name)
      setShowNewCenterForm(false)
      setNewCenterName('')
    } catch (err: any) {
      setCenterError(err.response?.data?.detail || err.message || 'Failed to create center')
    } finally {
      setCreatingCenter(false)
    }
  }

  const filteredPrompts = prompts.filter((p) =>
    p.prompt_type.toLowerCase().includes(searchQuery.toLowerCase())
  )

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      <h1 className="text-3xl font-bold text-gray-900 mb-8">Prompt Editor</h1>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
        <div className="lg:col-span-1">
          <div className="bg-white rounded-lg shadow p-4">
            {/* Center / group selector */}
            <div className="mb-4">
              <label className="block text-sm font-medium text-gray-700 mb-1">Center / group</label>
              <select
                value={selectedCenter}
                onChange={(e) => setSelectedCenter(e.target.value)}
                className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm"
              >
                {centers.map((c) => (
                  <option key={c} value={c}>{c}</option>
                ))}
              </select>
              <button
                type="button"
                onClick={() => setShowNewCenterForm(!showNewCenterForm)}
                className="mt-2 w-full px-3 py-1.5 text-sm text-gray-600 border border-gray-300 rounded-md hover:bg-gray-50"
              >
                + New group
              </button>
              {showNewCenterForm && (
                <div className="mt-2 p-2 bg-gray-50 rounded-md border border-gray-200">
                  <input
                    type="text"
                    placeholder="Center name (e.g. MSCI, VGR)"
                    value={newCenterName}
                    onChange={(e) => setNewCenterName(e.target.value)}
                    className="w-full px-2 py-1 border border-gray-300 rounded text-sm mb-2"
                  />
                  {centerError && <div className="text-red-600 text-xs mb-1">{centerError}</div>}
                  <div className="flex gap-1">
                    <button
                      onClick={handleCreateCenter}
                      disabled={creatingCenter || !newCenterName.trim()}
                      className="flex-1 px-2 py-1 bg-primary-600 text-white rounded text-sm disabled:opacity-50"
                    >
                      {creatingCenter ? 'Creating...' : 'Create'}
                    </button>
                    <button
                      type="button"
                      onClick={() => { setShowNewCenterForm(false); setNewCenterName(''); setCenterError(null); }}
                      className="px-2 py-1 bg-gray-200 text-gray-700 rounded text-sm"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              )}
            </div>

            <div className="mb-4">
              <button
                onClick={() => setShowCreateForm(!showCreateForm)}
                className="w-full px-4 py-2 bg-green-600 text-white rounded-md hover:bg-green-700 text-sm font-medium mb-4"
              >
                {showCreateForm ? 'Cancel' : '+ Create New Prompt'}
              </button>
              {showCreateForm && (
                <div className="mb-4 p-3 bg-gray-50 rounded-md border border-gray-200">
                  <input
                    type="text"
                    placeholder="Prompt name (e.g., new-prompt-int)"
                    value={newPromptName}
                    onChange={(e) => setNewPromptName(e.target.value)}
                    className="w-full px-2 py-1 border border-gray-300 rounded-md text-sm mb-2"
                  />
                  <textarea
                    placeholder="Prompt template (use {{note_original_text}} and {few_shot_examples} as placeholders)"
                    value={newPromptTemplate}
                    onChange={(e) => setNewPromptTemplate(e.target.value)}
                    rows={4}
                    className="w-full px-2 py-1 border border-gray-300 rounded-md text-sm mb-2 font-mono text-xs"
                  />
                  {error && (
                    <div className="text-red-600 text-xs mb-2">{error}</div>
                  )}
                  <button
                    onClick={handleCreatePrompt}
                    disabled={creating || !newPromptName.trim() || !newPromptTemplate.trim()}
                    className="w-full px-3 py-1 bg-primary-600 text-white rounded-md hover:bg-primary-700 disabled:opacity-50 disabled:cursor-not-allowed text-sm"
                  >
                    {creating ? 'Creating...' : 'Create'}
                  </button>
                </div>
              )}
            </div>
            <input
              type="text"
              placeholder="Search prompts..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-md mb-4"
            />
            <div className="space-y-1 max-h-[600px] overflow-y-auto">
              {loading ? (
                <div className="text-gray-500 text-sm">Loading...</div>
              ) : (
                filteredPrompts.map((prompt) => (
                  <button
                    key={prompt.prompt_type}
                    onClick={() => setSelectedPrompt(prompt.prompt_type)}
                    className={`w-full text-left px-3 py-2 rounded-md text-sm transition-colors ${
                      selectedPrompt === prompt.prompt_type
                        ? 'bg-primary-100 text-primary-900 font-medium'
                        : 'text-gray-700 hover:bg-gray-100'
                    }`}
                  >
                    {prompt.prompt_type}
                  </button>
                ))
              )}
            </div>
          </div>
        </div>

        <div className="lg:col-span-3">
          <div className="bg-white rounded-lg shadow p-6">
            {selectedPrompt && prompts.some((p) => p.prompt_type === selectedPrompt) ? (
              <PromptEditor
                promptType={selectedPrompt}
                center={selectedCenter}
                onSave={loadPrompts}
                onDelete={async () => {
                  setSelectedPrompt(null)
                  await loadPrompts()
                }}
              />
            ) : (
              <div className="text-gray-500 text-center py-12">
                Select a prompt to edit
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

