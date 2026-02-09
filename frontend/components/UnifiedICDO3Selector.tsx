'use client'

import { useState, useEffect, useCallback, useMemo } from 'react'
import {
  annotateApi,
  ICDO3SearchResult,
  ICDO3ValidationResult,
  UnifiedICDO3Code,
  ICDO3CodeInfo,
} from '@/lib/api'

interface UnifiedICDO3SelectorProps {
  sessionId: string
  noteId: string
  morphologyCode?: string  // From histology annotation
  topographyCode?: string  // From site annotation
  morphologyDescription?: string  // Description from histology
  topographyDescription?: string  // Description from site
  existingUnifiedCode?: UnifiedICDO3Code | null
  onSave?: (unifiedCode: UnifiedICDO3Code) => void
  onClose?: () => void
}

export default function UnifiedICDO3Selector({
  sessionId,
  noteId,
  morphologyCode,
  topographyCode,
  morphologyDescription,
  topographyDescription,
  existingUnifiedCode,
  onSave,
  onClose,
}: UnifiedICDO3SelectorProps) {
  // State
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState<ICDO3SearchResult[]>([])
  const [selectedCode, setSelectedCode] = useState<ICDO3SearchResult | null>(null)
  const [validation, setValidation] = useState<ICDO3ValidationResult | null>(null)
  const [isSearching, setIsSearching] = useState(false)
  const [isValidating, setIsValidating] = useState(false)
  const [isSaving, setIsSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [savedCode, setSavedCode] = useState<UnifiedICDO3Code | null>(existingUnifiedCode || null)

  // Debounced search
  const [debouncedQuery, setDebouncedQuery] = useState('')

  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedQuery(searchQuery)
    }, 300)
    return () => clearTimeout(timer)
  }, [searchQuery])

  // Validate combination when morphology and topography are provided
  useEffect(() => {
    if (morphologyCode && topographyCode) {
      validateCombination()
    }
  }, [morphologyCode, topographyCode])

  // Search when query changes
  useEffect(() => {
    if (debouncedQuery.trim()) {
      performSearch(debouncedQuery)
    } else {
      setSearchResults([])
    }
  }, [debouncedQuery])

  const validateCombination = async () => {
    if (!morphologyCode || !topographyCode) return

    setIsValidating(true)
    setError(null)

    try {
      const result = await annotateApi.validateICDO3Combination(morphologyCode, topographyCode)
      setValidation(result)

      // If valid, auto-select the combined code
      if (result.valid && result.query_code) {
        setSelectedCode({
          query_code: result.query_code,
          morphology_code: morphologyCode,
          topography_code: topographyCode,
          name: result.name || '',
          match_score: 1.0,
        })
      }
    } catch (err) {
      console.error('Validation error:', err)
      setError('Failed to validate code combination')
    } finally {
      setIsValidating(false)
    }
  }

  const performSearch = async (query: string) => {
    setIsSearching(true)
    setError(null)

    try {
      const response = await annotateApi.searchICDO3Codes(query, undefined, undefined, 20)
      setSearchResults(response.results)
    } catch (err) {
      console.error('Search error:', err)
      setError('Failed to search ICD-O-3 codes')
    } finally {
      setIsSearching(false)
    }
  }

  const handleSave = async () => {
    if (!selectedCode) return

    setIsSaving(true)
    setError(null)

    try {
      const response = await annotateApi.saveUnifiedICDO3Code(
        sessionId,
        noteId,
        selectedCode.query_code
      )

      if (response.success && response.unified_code) {
        setSavedCode(response.unified_code)
        onSave?.(response.unified_code)
      } else {
        setError(response.message || 'Failed to save unified code')
      }
    } catch (err) {
      console.error('Save error:', err)
      setError('Failed to save unified code')
    } finally {
      setIsSaving(false)
    }
  }

  const handleSelectResult = (result: ICDO3SearchResult) => {
    setSelectedCode(result)
  }

  // Computed values
  const combinedCode = useMemo(() => {
    if (morphologyCode && topographyCode) {
      return `${morphologyCode}-${topographyCode}`
    }
    return null
  }, [morphologyCode, topographyCode])

  const isValidCombination = validation?.valid === true
  const hasExtractedCodes = Boolean(morphologyCode || topographyCode)

  return (
    <div className="bg-white rounded-lg border border-gray-200 shadow-lg overflow-hidden">
      {/* Header */}
      <div className="bg-indigo-50 border-b border-indigo-200 px-4 py-3">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-indigo-900">
            Unified ICD-O-3 Diagnosis Code
          </h3>
          {onClose && (
            <button
              onClick={onClose}
              className="text-gray-400 hover:text-gray-600 text-lg font-bold"
            >
              x
            </button>
          )}
        </div>
        <p className="text-xs text-indigo-700 mt-1">
          Combine histology and topography codes into a validated diagnosis code
        </p>
      </div>

      <div className="p-4 space-y-4">
        {/* Extracted Codes Section */}
        {hasExtractedCodes && (
          <div className="bg-gray-50 rounded-md p-3 border border-gray-200">
            <div className="text-xs font-medium text-gray-600 mb-2">
              Extracted from annotations:
            </div>
            <div className="space-y-2">
              {/* Histology/Morphology */}
              <div className="flex items-center gap-2">
                <span className="text-xs font-medium text-gray-700 w-20">Histology:</span>
                {morphologyCode ? (
                  <>
                    <span className="font-mono text-sm bg-white px-2 py-1 rounded border border-gray-300">
                      {morphologyCode}
                    </span>
                    {morphologyDescription && (
                      <span className="text-xs text-gray-600 truncate max-w-48">
                        {morphologyDescription}
                      </span>
                    )}
                    {validation && (
                      <span className={`text-xs px-1.5 py-0.5 rounded ${
                        validation.morphology_valid
                          ? 'bg-green-100 text-green-700'
                          : 'bg-red-100 text-red-700'
                      }`}>
                        {validation.morphology_valid ? 'Valid' : 'Invalid'}
                      </span>
                    )}
                  </>
                ) : (
                  <span className="text-xs text-gray-400 italic">Not extracted</span>
                )}
              </div>

              {/* Site/Topography */}
              <div className="flex items-center gap-2">
                <span className="text-xs font-medium text-gray-700 w-20">Site:</span>
                {topographyCode ? (
                  <>
                    <span className="font-mono text-sm bg-white px-2 py-1 rounded border border-gray-300">
                      {topographyCode}
                    </span>
                    {topographyDescription && (
                      <span className="text-xs text-gray-600 truncate max-w-48">
                        {topographyDescription}
                      </span>
                    )}
                    {validation && (
                      <span className={`text-xs px-1.5 py-0.5 rounded ${
                        validation.topography_valid
                          ? 'bg-green-100 text-green-700'
                          : 'bg-red-100 text-red-700'
                      }`}>
                        {validation.topography_valid ? 'Valid' : 'Invalid'}
                      </span>
                    )}
                  </>
                ) : (
                  <span className="text-xs text-gray-400 italic">Not extracted</span>
                )}
              </div>
            </div>
          </div>
        )}

        {/* Combined Code Validation */}
        {combinedCode && (
          <div className={`rounded-md p-3 border ${
            isValidating
              ? 'bg-gray-50 border-gray-200'
              : isValidCombination
              ? 'bg-green-50 border-green-200'
              : 'bg-red-50 border-red-200'
          }`}>
            <div className="flex items-center gap-3">
              <span className="text-xs font-medium text-gray-700">Combined Code:</span>
              <span className="font-mono text-sm font-bold bg-white px-2 py-1 rounded border border-gray-300">
                {combinedCode}
              </span>
              {isValidating ? (
                <span className="text-xs text-gray-500">Validating...</span>
              ) : isValidCombination ? (
                <span className="text-xs px-2 py-1 rounded bg-green-100 text-green-800 font-medium">
                  Valid
                </span>
              ) : (
                <span className="text-xs px-2 py-1 rounded bg-red-100 text-red-800 font-medium">
                  Invalid Combination
                </span>
              )}
            </div>
            {validation?.name && (
              <div className="mt-2 text-sm text-gray-700">
                "{validation.name}"
              </div>
            )}
            {!isValidCombination && !isValidating && (
              <div className="mt-2 text-xs text-red-600">
                This combination does not exist in the ICD-O-3 reference. Use the search below to find a valid code.
              </div>
            )}
          </div>
        )}

        {/* Search Section */}
        <div className="border-t border-gray-200 pt-4">
          <div className="text-xs font-medium text-gray-600 mb-2">
            Search for ICD-O-3 code:
          </div>
          <div className="relative">
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search by name or code (e.g., 'carcinoma' or '8031/3')..."
              className="w-full px-3 py-2 text-sm border border-gray-300 rounded-md focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
            />
            {isSearching && (
              <div className="absolute right-3 top-1/2 -translate-y-1/2">
                <svg className="animate-spin h-4 w-4 text-indigo-500" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                </svg>
              </div>
            )}
          </div>

          {/* Search Results */}
          {searchResults.length > 0 && (
            <div className="mt-3 max-h-60 overflow-y-auto border border-gray-200 rounded-md">
              {searchResults.map((result, index) => (
                <label
                  key={`${result.query_code}-${index}`}
                  className={`flex items-start gap-3 p-3 cursor-pointer transition-colors border-b border-gray-100 last:border-b-0 ${
                    selectedCode?.query_code === result.query_code
                      ? 'bg-indigo-50 border-l-4 border-l-indigo-500'
                      : 'hover:bg-gray-50'
                  }`}
                >
                  <input
                    type="radio"
                    name="icdo3-search-result"
                    checked={selectedCode?.query_code === result.query_code}
                    onChange={() => handleSelectResult(result)}
                    className="mt-1 h-4 w-4 text-indigo-600 border-gray-300 focus:ring-indigo-500"
                  />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-mono text-sm font-semibold text-indigo-800">
                        {result.query_code}
                      </span>
                      <span className={`text-xs px-2 py-0.5 rounded ${
                        result.match_score >= 0.8
                          ? 'bg-green-100 text-green-800'
                          : result.match_score >= 0.5
                          ? 'bg-yellow-100 text-yellow-800'
                          : 'bg-gray-100 text-gray-800'
                      }`}>
                        {(result.match_score * 100).toFixed(0)}%
                      </span>
                    </div>
                    <div className="text-sm text-gray-700 mt-1">
                      {result.name}
                    </div>
                    <div className="text-xs text-gray-500 mt-1">
                      Morphology: <span className="font-mono">{result.morphology_code}</span>
                      {' | '}
                      Topography: <span className="font-mono">{result.topography_code}</span>
                    </div>
                  </div>
                </label>
              ))}
            </div>
          )}

          {searchQuery && !isSearching && searchResults.length === 0 && (
            <div className="mt-3 text-sm text-gray-500 italic text-center py-4">
              No results found for "{searchQuery}"
            </div>
          )}
        </div>

        {/* Selected Code Summary */}
        {selectedCode && (
          <div className="bg-indigo-50 border border-indigo-200 rounded-md p-3">
            <div className="text-xs font-medium text-indigo-700 mb-2">Selected Code:</div>
            <div className="flex items-center gap-2">
              <span className="font-mono text-sm font-bold bg-white px-3 py-1.5 rounded border border-indigo-300 text-indigo-900">
                {selectedCode.query_code}
              </span>
            </div>
            <div className="text-sm text-gray-700 mt-2">
              {selectedCode.name}
            </div>
          </div>
        )}

        {/* Saved Code Display */}
        {savedCode && (
          <div className="bg-green-50 border border-green-200 rounded-md p-3">
            <div className="flex items-center gap-2 mb-2">
              <span className="text-green-600 font-bold">Saved</span>
              <span className="font-mono text-sm font-bold bg-white px-3 py-1.5 rounded border border-green-300 text-green-900">
                {savedCode.query_code}
              </span>
            </div>
            <div className="text-sm text-gray-700">{savedCode.name}</div>
            <div className="text-xs text-gray-500 mt-1">
              Source: {savedCode.source} | User Selected: {savedCode.user_selected ? 'Yes' : 'No'}
            </div>
          </div>
        )}

        {/* Error Display */}
        {error && (
          <div className="bg-red-50 border border-red-200 rounded-md p-3 text-sm text-red-700">
            {error}
          </div>
        )}

        {/* Actions */}
        <div className="flex items-center justify-end gap-3 pt-2 border-t border-gray-200">
          {onClose && (
            <button
              onClick={onClose}
              className="px-4 py-2 text-sm text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50"
            >
              Cancel
            </button>
          )}
          <button
            onClick={handleSave}
            disabled={!selectedCode || isSaving}
            className={`px-4 py-2 text-sm font-medium rounded-md ${
              selectedCode && !isSaving
                ? 'bg-indigo-600 text-white hover:bg-indigo-700'
                : 'bg-gray-200 text-gray-500 cursor-not-allowed'
            }`}
          >
            {isSaving ? (
              <span className="flex items-center gap-2">
                <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                </svg>
                Saving...
              </span>
            ) : (
              'Save Selection'
            )}
          </button>
        </div>
      </div>
    </div>
  )
}
