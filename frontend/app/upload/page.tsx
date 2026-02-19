'use client'

import { useState, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { uploadApi, promptsApi, sessionsApi } from '@/lib/api'
import type { CSVUploadResponse, PromptInfo, CSVRow } from '@/lib/api'
import { useDefaultCenter } from '@/lib/useDefaultCenter'

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
  const [reportTypeMapping, setReportTypeMapping] = useState<Record<string, string[]>>({})
  const [savedMappings, setSavedMappings] = useState<Record<string, string[]>>({})

  useEffect(() => {
    promptsApi.listCenters().then(setCenters).catch(console.error)
    loadFewshotsStatus()
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

  const loadFewshotsStatus = async () => {
    try {
      const status = await uploadApi.getFewshotsStatus()
      setFewshotStatus(status)
    } catch (err) {
      console.error('Failed to load few-shots status:', err)
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

    setFewshotUploading(true)
    setError(null)

    try {
      const result = await uploadApi.uploadFewshots(fewshotFile)
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
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || 'Failed to delete few-shot examples')
    } finally {
      setFewshotDeleting(false)
    }
  }

  const loadSavedMappings = async () => {
    try {
      const mappings = await uploadApi.getReportTypeMappings()
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
      
      // Load saved mappings first
      const mappings = await uploadApi.getReportTypeMappings()
      setSavedMappings(mappings)
      
      // Initialize mapping: if we have saved mappings for these report types, use them
      // Otherwise, initialize with all prompts selected for each report type
      const initialMapping: Record<string, string[]> = {}
      if (result.report_types) {
        for (const reportType of result.report_types) {
          if (mappings[reportType]) {
            initialMapping[reportType] = mappings[reportType]
          } else {
            // Default: all prompts selected
            initialMapping[reportType] = prompts.map(p => p.prompt_type)
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
      
      // Save the mapping for future use
      await uploadApi.saveReportTypeMappings(reportTypeMapping)
      
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
          </p>
          <div className="text-xs text-gray-500 mb-4 bg-gray-50 p-3 rounded">
            <strong>Required columns:</strong> <code className="bg-white px-1 rounded">prompt_type</code>, <code className="bg-white px-1 rounded">note_text</code>, <code className="bg-white px-1 rounded">annotation</code>
            <br />
            <strong>Example:</strong> <code className="bg-white px-1 rounded">gender-int,"Patient is a 65-year-old male...","Patient's gender male."</code>
            <br />
            <a href="/fewshots_example.csv" download className="text-blue-600 hover:underline">Download example CSV</a>
          </div>
          
          {fewshotStatus && (
            <div className="mb-4 p-3 bg-blue-50 border border-blue-200 rounded-md">
              <div className="text-sm">
                <div className="flex justify-between items-start mb-1">
                  <div className="font-medium text-blue-900">Few-Shot Status:</div>
                  <button
                    onClick={handleFewshotDelete}
                    disabled={fewshotDeleting || !fewshotStatus.simple_fewshots_available}
                    className="text-red-600 hover:text-red-800 disabled:opacity-50 disabled:cursor-not-allowed text-sm font-medium"
                    title={fewshotStatus.simple_fewshots_available ? "Delete all few-shot examples" : "No few-shot examples to delete"}
                  >
                    {fewshotDeleting ? 'Deleting...' : 'Delete'}
                  </button>
                </div>
                <div className="text-blue-700">
                  {fewshotStatus.faiss_available && (
                    <span className="inline-block mr-2">✓ FAISS available</span>
                  )}
                  {fewshotStatus.simple_fewshots_available && (
                    <span className="inline-block mr-2">
                      ✓ {fewshotStatus.total_examples} examples uploaded
                      ({Object.keys(fewshotStatus.counts_by_prompt).length} prompt types)
                    </span>
                  )}
                  {!fewshotStatus.faiss_available && !fewshotStatus.simple_fewshots_available && (
                    <span className="text-gray-600">No few-shot examples available (zero-shot mode)</span>
                  )}
                </div>
              </div>
            </div>
          )}
          
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
                            const currentPrompts = reportTypeMapping[reportType] || []
                            if (currentPrompts.length === prompts.length) {
                              setReportTypeMapping({
                                ...reportTypeMapping,
                                [reportType]: []
                              })
                            } else {
                              setReportTypeMapping({
                                ...reportTypeMapping,
                                [reportType]: prompts.map(p => p.prompt_type)
                              })
                            }
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
                                const currentPrompts = reportTypeMapping[reportType] || []
                                if (e.target.checked) {
                                  setReportTypeMapping({
                                    ...reportTypeMapping,
                                    [reportType]: [...currentPrompts, prompt.prompt_type]
                                  })
                                } else {
                                  setReportTypeMapping({
                                    ...reportTypeMapping,
                                    [reportType]: currentPrompts.filter((p) => p !== prompt.prompt_type)
                                  })
                                }
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

