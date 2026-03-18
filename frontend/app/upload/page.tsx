'use client'

import { useState, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { uploadApi, promptsApi, sessionsApi, presetsApi } from '@/lib/api'
import type { CSVUploadResponse, PromptInfo, CSVRow } from '@/lib/api'
import PresetSelector from '@/components/PresetSelector'
import { useDefaultCenter } from '@/lib/useDefaultCenter'
import { useFewshotK } from '@/lib/useFewshotK'

export default function UploadPage() {
  const router = useRouter()
  const [selectedCenter, setSelectedCenter] = useDefaultCenter()
  const [centers, setCenters] = useState<string[]>([])
  const [file, setFile] = useState<File | null>(null)
  const [uploading, setUploading] = useState(false)
  const [uploadResult, setUploadResult] = useState<CSVUploadResponse | null>(null)
  const [prompts, setPrompts] = useState<PromptInfo[]>([])
  const [selectedPrompts, setSelectedPrompts] = useState<string[]>([])
  const [sessionName, setSessionName] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [fewshotFile, setFewshotFile] = useState<File | null>(null)
  const [fewshotUploading, setFewshotUploading] = useState(false)
  const [fewshotStatus, setFewshotStatus] = useState<any>(null)
  const [fewshotDeleting, setFewshotDeleting] = useState(false)
  const [fewshotDownloading, setFewshotDownloading] = useState(false)
  const [fewshotCenter, setFewshotCenter] = useState<string>(selectedCenter)
  const [fewshotLoading, setFewshotLoading] = useState(false)
  const { standardK, setStandardK, fastK, setFastK } = useFewshotK()
  const [reportTypeMapping, setReportTypeMapping] = useState<Record<string, string[]>>({})
  const [savedMappings, setSavedMappings] = useState<Record<string, string[]>>({})

  useEffect(() => {
    promptsApi.listCenters().then(setCenters).catch(console.error)
  }, [])

  useEffect(() => {
    if (centers.length > 0 && !centers.includes(selectedCenter)) {
      setSelectedCenter(centers[0])
    }
  }, [centers, selectedCenter, setSelectedCenter])

  useEffect(() => {
    if (selectedCenter) {
      loadPrompts()
    }
  }, [selectedCenter])

  // Load fewshot status on mount and whenever fewshot center changes
  useEffect(() => {
    if (fewshotCenter) {
      loadFewshotsStatus(fewshotCenter)
    }
  }, [fewshotCenter])

  const loadFewshotsStatus = async (center?: string) => {
    const c = center || fewshotCenter
    if (!c) return
    setFewshotLoading(true)
    try {
      const status = await uploadApi.getFewshotsStatus(c)
      setFewshotStatus(status)
    } catch (err) {
      console.error('Failed to load few-shots status:', err)
    } finally {
      setFewshotLoading(false)
    }
  }

  const loadPrompts = async () => {
    try {
      const data = await promptsApi.list(selectedCenter)
      setPrompts(data)
    } catch (err) {
      console.error('Failed to load prompts:', err)
    }
  }

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      setFile(e.target.files[0])
      setUploadResult(null)
      setError(null)
    }
  }

  const handleFewshotFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      setFewshotFile(e.target.files[0])
    }
  }

  const handleFewshotUpload = async () => {
    if (!fewshotFile) {
      setError('Please select a few-shot examples file')
      return
    }
    if (!fewshotCenter) {
      setError('Please select a center for the few-shot examples')
      return
    }

    setFewshotUploading(true)
    setError(null)

    try {
      const result = await uploadApi.uploadFewshots(fewshotFile, fewshotCenter)
      await loadFewshotsStatus()
      setFewshotFile(null)
      // Reset file input
      const fileInput = document.getElementById('fewshot-file-input') as HTMLInputElement
      if (fileInput) fileInput.value = ''
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || 'Few-shot upload failed')
    } finally {
      setFewshotUploading(false)
    }
  }

  const handleFewshotDelete = async () => {
    if (!fewshotStatus) {
      return
    }

    if (!fewshotStatus.simple_fewshots_available) {
      alert('No simple few-shot examples to delete. Only FAISS examples are available.')
      return
    }

    if (!confirm('Are you sure you want to delete all few-shot examples? This action cannot be undone.')) {
      return
    }

    setFewshotDeleting(true)
    setError(null)

    try {
      await uploadApi.deleteFewshots()
      await loadFewshotsStatus()
      setFewshotCenter(centers.length > 0 ? centers[0] : '')
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || 'Failed to delete few-shot examples')
    } finally {
      setFewshotDeleting(false)
    }
  }

  const handleFewshotDownload = async () => {
    if (!fewshotCenter) {
      setError('Please select a center to download few-shot examples for')
      return
    }
    setFewshotDownloading(true)
    setError(null)
    try {
      const blob = await uploadApi.downloadFewshots(fewshotCenter)
      const url = window.URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `fewshots_${fewshotCenter.toLowerCase()}.csv`
      document.body.appendChild(a)
      a.click()
      a.remove()
      window.URL.revokeObjectURL(url)
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || 'Failed to download few-shot examples')
    } finally {
      setFewshotDownloading(false)
    }
  }

  const loadSavedMappings = async () => {
    try {
      const mappings = await uploadApi.getReportTypeMappings(selectedCenter)
      setSavedMappings(mappings)
    } catch (err) {
      console.error('Failed to load saved mappings:', err)
    }
  }

  const handleUpload = async () => {
    if (!file) {
      setError('Please select a file')
      return
    }

    setUploading(true)
    setError(null)

    try {
      const result = await uploadApi.uploadCSV(file)
      setUploadResult(result)
      setSessionName(file.name.replace('.csv', ''))
      
      // Load saved mappings for the selected center
      const mappings = await uploadApi.getReportTypeMappings(selectedCenter)
      setSavedMappings(mappings)
      
      // Initialize mapping: if we have saved mappings for these report types, use them
      // Otherwise, initialize with all prompts selected for each report type
      const initialMapping: Record<string, string[]> = {}
      if (result.report_types) {
        for (const reportType of result.report_types) {
          if (mappings[reportType]) {
            initialMapping[reportType] = mappings[reportType]
          } else {
            // Default: no prompts selected — user must explicitly choose
            initialMapping[reportType] = []
          }
        }
      }
      setReportTypeMapping(initialMapping)
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || 'Upload failed')
    } finally {
      setUploading(false)
    }
  }

  const handleCreateSession = async () => {
    if (!uploadResult) {
      setError('Please upload a CSV file first')
      return
    }

    // Validate that at least one prompt is selected for each report type
    const allReportTypes = uploadResult.report_types || []
    const hasMapping = allReportTypes.every(rt => 
      reportTypeMapping[rt] && reportTypeMapping[rt].length > 0
    )
    
    if (!hasMapping) {
      setError('Please select at least one prompt type for each report type')
      return
    }

    try {
      // Use all_rows (all data) instead of preview (only 10 rows) for session creation
      const csvData: CSVRow[] = (uploadResult.all_rows || uploadResult.preview).map((row: any) => ({
        text: row.text || '',
        date: row.date || '',
        p_id: row.p_id || '',
        note_id: row.note_id || '',
        report_type: row.report_type || '',
        annotations: row.annotations,
      }))

      // Determine evaluation mode based on has_annotations from upload result
      const evaluationMode = uploadResult.has_annotations ? 'evaluation' : 'validation'
      
      // Collect all unique prompt types from the mapping
      const allPromptTypes = new Set<string>()
      Object.values(reportTypeMapping).forEach(promptTypes => {
        promptTypes.forEach(pt => allPromptTypes.add(pt))
      })
      
      // Save the mapping for future use, scoped to selected center
      await uploadApi.saveReportTypeMappings(reportTypeMapping, selectedCenter)
      
      const session = await sessionsApi.create(
        sessionName || file?.name?.replace('.csv', '') || 'Untitled Session',
        csvData,
        Array.from(allPromptTypes),
        evaluationMode,
        undefined,
        reportTypeMapping
      )

      router.push(`/annotate/${session.session_id}`)
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || 'Failed to create session')
    }
  }

  return (
    <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      <div className="flex items-center justify-between mb-8">
        <h1 className="text-3xl font-bold text-gray-900">Upload CSV</h1>
        {centers.length > 0 && (
          <div className="flex items-center">
            <label className="text-sm font-medium text-gray-700 mr-2">Center / group:</label>
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
      </div>

      <div className="bg-white rounded-lg shadow p-6 space-y-6">
        {/* Few-shot Examples Upload Section */}
        <div className="border-b border-gray-200 pb-6">
          <h2 className="text-lg font-semibold text-gray-900 mb-4">Few-Shot Examples (Optional)</h2>
          <p className="text-sm text-gray-600 mb-4">
            Upload a CSV file with few-shot examples to improve annotation quality.
            Select the center these examples belong to.
          </p>
          <div className="text-xs text-gray-500 mb-4 bg-gray-50 p-3 rounded">
            <strong>Required columns:</strong> <code className="bg-white px-1 rounded">prompt_type</code>, <code className="bg-white px-1 rounded">note_text</code>, <code className="bg-white px-1 rounded">annotation</code>
            <br />
            <strong>Example:</strong> <code className="bg-white px-1 rounded">gender,"Patient is a 65-year-old male...","Patient's gender male."</code>
            <br />
            <span className="text-gray-400">Note: prompt_type should be the base name (e.g., &quot;gender&quot;, not &quot;gender-int-sarc&quot;). The center suffix is added automatically.</span>
            <br />
            <a href="/fewshots_example.csv" download className="text-blue-600 hover:underline">Download example CSV</a>
          </div>

          <div className="mb-4">
            <label className="block text-sm font-medium text-gray-700 mb-1">Center for Few-Shots</label>
            <select
              value={fewshotCenter}
              onChange={(e) => setFewshotCenter(e.target.value)}
              className="block w-full max-w-xs rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500 sm:text-sm"
            >
              {centers.map((c) => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
          </div>
          
          {fewshotLoading ? (
            <div className="mb-4 p-3 rounded-md border bg-gray-50 border-gray-200">
              <div className="text-sm font-medium text-gray-500">Loading fewshot status...</div>
            </div>
          ) : fewshotStatus && (
            <div className={`mb-4 p-3 rounded-md border ${fewshotStatus.simple_fewshots_available ? 'bg-green-50 border-green-200' : 'bg-amber-50 border-amber-200'}`}>
              <div className="flex justify-between items-center">
                <div className="text-sm font-medium">
                  {fewshotStatus.simple_fewshots_available ? (
                    <span className="text-green-800">
                      Fewshots are properly configured ({fewshotStatus.total_examples} examples, {Object.keys(fewshotStatus.counts_by_prompt).length} prompt types)
                    </span>
                  ) : (
                    <span className="text-amber-800">
                      Fewshots are missing for {fewshotCenter || 'this center'}
                    </span>
                  )}
                </div>
                {fewshotStatus.simple_fewshots_available && (
                  <div className="flex gap-3">
                    <button
                      onClick={handleFewshotDownload}
                      disabled={fewshotDownloading}
                      className="text-blue-600 hover:text-blue-800 disabled:opacity-50 disabled:cursor-not-allowed text-sm font-medium"
                    >
                      {fewshotDownloading ? 'Downloading...' : 'Download CSV'}
                    </button>
                    <button
                      onClick={handleFewshotDelete}
                      disabled={fewshotDeleting}
                      className="text-red-600 hover:text-red-800 disabled:opacity-50 disabled:cursor-not-allowed text-sm font-medium"
                    >
                      {fewshotDeleting ? 'Deleting...' : 'Delete'}
                    </button>
                  </div>
                )}
              </div>
            </div>
          )}

          <div className="mb-4 flex gap-6">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Standard mode examples (k)</label>
              <input
                type="number"
                min={1}
                max={10}
                value={standardK}
                onChange={(e) => setStandardK(parseInt(e.target.value, 10) || 1)}
                className="block w-20 rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500 sm:text-sm"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Fast mode examples (k)</label>
              <input
                type="number"
                min={1}
                max={5}
                value={fastK}
                onChange={(e) => setFastK(parseInt(e.target.value, 10) || 1)}
                className="block w-20 rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500 sm:text-sm"
              />
            </div>
          </div>
          
          <div className="flex gap-2">
            <input
              id="fewshot-file-input"
              type="file"
              accept=".csv"
              onChange={handleFewshotFileChange}
              className="block flex-1 text-sm text-gray-500 file:mr-4 file:py-2 file:px-4 file:rounded-md file:border-0 file:text-sm file:font-semibold file:bg-blue-50 file:text-blue-700 hover:file:bg-blue-100"
            />
            {fewshotFile && (
              <button
                onClick={handleFewshotUpload}
                disabled={fewshotUploading}
                className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {fewshotUploading ? 'Uploading...' : 'Upload Few-Shots'}
              </button>
            )}
          </div>
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">
            CSV File (Patient Notes)
          </label>
          <input
            type="file"
            accept=".csv"
            onChange={handleFileChange}
            className="block w-full text-sm text-gray-500 file:mr-4 file:py-2 file:px-4 file:rounded-md file:border-0 file:text-sm file:font-semibold file:bg-primary-50 file:text-primary-700 hover:file:bg-primary-100"
          />
          <p className="mt-1 text-sm text-gray-500">
            Expected columns: text, date, p_id, note_id, report_type (optional: annotations)
          </p>
        </div>

        {file && (
          <button
            onClick={handleUpload}
            disabled={uploading}
            className="w-full px-4 py-2 bg-primary-600 text-white rounded-md hover:bg-primary-700 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {uploading ? 'Uploading...' : 'Upload & Parse'}
          </button>
        )}

        {error && (
          <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded">
            {error}
          </div>
        )}

        {uploadResult && (
          <div className="space-y-4">
            <div className="bg-green-50 border border-green-200 text-green-700 px-4 py-3 rounded">
              {uploadResult.message}
            </div>

            {uploadResult.duplicate_note_ids_detected && (
              <div className="bg-yellow-50 border border-yellow-300 text-yellow-800 px-4 py-3 rounded">
                <strong>Warning: Duplicate Note IDs detected.</strong> Your CSV contained rows with the same <code>note_id</code> value. Each note ID has been made unique by appending its row index (e.g. <code>1</code> → <code>1_3</code>). Annotations are keyed by Note ID, so duplicates would otherwise cause all affected notes to share the same annotation. Check your CSV file if this is unexpected.
              </div>
            )}

            {uploadResult.duplicate_text_detected && (
              <div className="bg-orange-50 border border-orange-300 text-orange-800 px-4 py-3 rounded">
                <strong>Warning: Duplicate text content removed.</strong>{' '}
                {uploadResult.duplicate_text_removed_count} row
                {uploadResult.duplicate_text_removed_count !== 1 ? 's were' : ' was'} removed
                because {uploadResult.duplicate_text_removed_count !== 1 ? 'their' : 'its'} text
                content was identical to an earlier row (comparison is case-insensitive and
                whitespace-normalized). The first occurrence of each unique note was kept.
                {uploadResult.duplicate_text_note_ids && uploadResult.duplicate_text_note_ids.length > 0 && (
                  <div className="mt-2 text-sm">
                    <span className="font-medium">Removed Note IDs: </span>
                    <code className="bg-orange-100 px-1 rounded">
                      {uploadResult.duplicate_text_note_ids.join(', ')}
                    </code>
                  </div>
                )}
              </div>
            )}

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Session Name
              </label>
              <input
                type="text"
                value={sessionName}
                onChange={(e) => setSessionName(e.target.value)}
                className="w-full px-3 py-2 border border-gray-300 rounded-md"
                placeholder="Enter session name"
              />
            </div>

            {/* Preset Selector */}
            {uploadResult.report_types && uploadResult.report_types.length > 0 && (
              <PresetSelector
                center={selectedCenter}
                currentMapping={reportTypeMapping}
                onLoadPreset={(presetMapping) => {
                  setReportTypeMapping((prev) => {
                    const merged = { ...prev }
                    for (const rt of uploadResult.report_types || []) {
                      if (presetMapping[rt]) {
                        merged[rt] = presetMapping[rt]
                      }
                    }
                    return merged
                  })
                }}
                reportTypes={uploadResult.report_types}
              />
            )}

            {/* Report Type to Prompt Type Mapping */}
            {uploadResult.report_types && uploadResult.report_types.length > 0 && (
              <div>
                <div className="flex justify-between items-center mb-2">
                  <label className="block text-sm font-medium text-gray-700">
                    Map Report Types to Prompt Types
                  </label>
                  <span className="text-xs text-gray-500">
                    Select which prompts to run for each report type
                  </span>
                </div>
                <div className="space-y-4 border border-gray-300 rounded-md p-4">
                  {uploadResult.report_types.map((reportType) => (
                    <div key={reportType} className="border-b border-gray-200 last:border-b-0 pb-4 last:pb-0">
                      <div className="flex items-center justify-between mb-2">
                        <h4 className="text-sm font-semibold text-gray-800">
                          {reportType}
                        </h4>
                        <button
                          type="button"
                          onClick={() => {
                            setReportTypeMapping((prev) => {
                              const currentPrompts = prev[reportType] || []
                              if (currentPrompts.length === prompts.length) {
                                return { ...prev, [reportType]: [] }
                              } else {
                                return { ...prev, [reportType]: prompts.map(p => p.prompt_type) }
                              }
                            })
                          }}
                          className="text-xs text-primary-600 hover:text-primary-700 font-medium"
                        >
                          {reportTypeMapping[reportType]?.length === prompts.length ? 'Deselect All' : 'Select All'}
                        </button>
                      </div>
                      <div className="grid grid-cols-2 md:grid-cols-3 gap-2 max-h-48 overflow-y-auto">
                        {prompts.map((prompt) => (
                          <label
                            key={prompt.prompt_type}
                            className="flex items-center space-x-2 py-1 text-sm"
                          >
                            <input
                              type="checkbox"
                              checked={reportTypeMapping[reportType]?.includes(prompt.prompt_type) || false}
                              onChange={(e) => {
                                const checked = e.target.checked
                                setReportTypeMapping((prev) => {
                                  const currentPrompts = prev[reportType] || []
                                  if (checked) {
                                    return { ...prev, [reportType]: [...currentPrompts, prompt.prompt_type] }
                                  } else {
                                    return { ...prev, [reportType]: currentPrompts.filter((p) => p !== prompt.prompt_type) }
                                  }
                                })
                              }}
                              className="rounded border-gray-300 text-primary-600 focus:ring-primary-500"
                            />
                            <span className="text-gray-700">{prompt.prompt_type}</span>
                          </label>
                        ))}
                      </div>
                      {reportTypeMapping[reportType] && reportTypeMapping[reportType].length > 0 && (
                        <div className="mt-2 text-xs text-gray-500">
                          {reportTypeMapping[reportType].length} prompt{reportTypeMapping[reportType].length !== 1 ? 's' : ''} selected
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}

            <div>
              <h3 className="text-sm font-medium text-gray-700 mb-2">Preview (first 10 rows)</h3>
              <div className="border border-gray-300 rounded-md overflow-x-auto">
                <table className="min-w-full divide-y divide-gray-200">
                  <thead className="bg-gray-50">
                    <tr>
                      {uploadResult.columns.map((col) => (
                        <th
                          key={col}
                          className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase"
                        >
                          {col}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="bg-white divide-y divide-gray-200">
                    {uploadResult.preview.map((row: any, idx: number) => (
                      <tr key={idx}>
                        {uploadResult.columns.map((col) => (
                          <td
                            key={col}
                            className="px-3 py-2 text-xs text-gray-700 max-w-xs truncate"
                            title={String(row[col] || '')}
                          >
                            {String(row[col] || '').substring(0, 50)}
                            {String(row[col] || '').length > 50 ? '...' : ''}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            <button
              onClick={handleCreateSession}
              disabled={
                !uploadResult.report_types || 
                uploadResult.report_types.length === 0 ||
                !uploadResult.report_types.every(rt => 
                  reportTypeMapping[rt] && reportTypeMapping[rt].length > 0
                )
              }
              className="w-full px-4 py-2 bg-primary-600 text-white rounded-md hover:bg-primary-700 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              Create Session & Start Annotation
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

