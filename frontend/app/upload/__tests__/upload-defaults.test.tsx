import { render, screen, waitFor, fireEvent, cleanup } from '@testing-library/react'
import { vi, describe, it, expect, beforeEach, afterEach } from 'vitest'
import UploadPage from '../page'

// --- Mocks ---

const mockPush = vi.fn()
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: mockPush }),
}))

const mockUploadCSV = vi.fn()
const mockGetFewshotsStatus = vi.fn()
const mockGetReportTypeMappings = vi.fn()
const mockSaveReportTypeMappings = vi.fn()
const mockPromptsList = vi.fn()
const mockPromptsListCenters = vi.fn()
const mockPresetsApiList = vi.fn()
const mockPresetsApiCreate = vi.fn()
const mockSessionsCreate = vi.fn()

vi.mock('@/lib/api', () => ({
  uploadApi: {
    uploadCSV: (...args: unknown[]) => mockUploadCSV(...args),
    getFewshotsStatus: () => mockGetFewshotsStatus(),
    getReportTypeMappings: () => mockGetReportTypeMappings(),
    saveReportTypeMappings: (...args: unknown[]) => mockSaveReportTypeMappings(...args),
  },
  promptsApi: {
    list: (...args: unknown[]) => mockPromptsList(...args),
    listCenters: () => mockPromptsListCenters(),
  },
  presetsApi: {
    list: (...args: unknown[]) => mockPresetsApiList(...args),
    create: (...args: unknown[]) => mockPresetsApiCreate(...args),
  },
  sessionsApi: {
    create: (...args: unknown[]) => mockSessionsCreate(...args),
  },
}))

vi.mock('@/lib/useDefaultCenter', () => ({
  useDefaultCenter: () => ['center-a', vi.fn()],
}))

const prompts = [
  { prompt_type: 'gender-int', description: 'Gender', system_prompt: '', user_prompt: '', center: 'center-a' },
  { prompt_type: 'diagnosis', description: 'Diagnosis', system_prompt: '', user_prompt: '', center: 'center-a' },
  { prompt_type: 'staging', description: 'Staging', system_prompt: '', user_prompt: '', center: 'center-a' },
]

const uploadResult = {
  message: 'Parsed 2 rows',
  columns: ['text', 'date', 'p_id', 'note_id', 'report_type'],
  preview: [
    { text: 'note1', date: '2024-01-01', p_id: 'p1', note_id: 'n1', report_type: 'Pathology' },
    { text: 'note2', date: '2024-01-02', p_id: 'p2', note_id: 'n2', report_type: 'Radiology' },
  ],
  all_rows: [
    { text: 'note1', date: '2024-01-01', p_id: 'p1', note_id: 'n1', report_type: 'Pathology' },
    { text: 'note2', date: '2024-01-02', p_id: 'p2', note_id: 'n2', report_type: 'Radiology' },
  ],
  report_types: ['Pathology', 'Radiology'],
  total_rows: 2,
  has_annotations: false,
}

describe('UploadPage – default prompt type selection', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockPromptsListCenters.mockResolvedValue(['center-a'])
    mockPromptsList.mockResolvedValue(prompts)
    mockGetFewshotsStatus.mockResolvedValue({ faiss_available: false, simple_fewshots_available: false })
    mockGetReportTypeMappings.mockResolvedValue({})
    mockUploadCSV.mockResolvedValue(uploadResult)
    mockPresetsApiList.mockResolvedValue([])
  })

  afterEach(() => {
    cleanup()
  })

  it('initializes report type mapping with empty arrays when no saved mapping exists', async () => {
    render(<UploadPage />)

    await waitFor(() => {
      expect(mockPromptsList).toHaveBeenCalled()
    })

    // Simulate file selection and upload
    const fileInputs = document.querySelectorAll('input[type="file"][accept=".csv"]')
    const fileInput = fileInputs[1] as HTMLInputElement
    const file = new File(['text,date,p_id,note_id,report_type\nnote1,2024-01-01,p1,n1,Pathology'], 'test.csv', {
      type: 'text/csv',
    })
    fireEvent.change(fileInput, { target: { files: [file] } })

    const uploadButton = screen.getByRole('button', { name: /Upload & Parse/i })
    fireEvent.click(uploadButton)

    await waitFor(() => {
      expect(screen.getByText('Parsed 2 rows')).toBeInTheDocument()
    })

    // No checkboxes should be checked — default is empty, not all prompts
    const checkboxes = screen.getAllByRole('checkbox') as HTMLInputElement[]
    const checkedBoxes = checkboxes.filter(cb => cb.checked)
    expect(checkedBoxes.length).toBe(0)
  })

  it('uses saved mapping when one exists for a report type', async () => {
    // Saved mapping: Pathology has only 'diagnosis' selected
    mockGetReportTypeMappings.mockResolvedValue({
      Pathology: ['diagnosis'],
    })

    render(<UploadPage />)

    await waitFor(() => {
      expect(mockPromptsList).toHaveBeenCalled()
    })

    const fileInputs = document.querySelectorAll('input[type="file"][accept=".csv"]')
    const fileInput = fileInputs[1] as HTMLInputElement
    const file = new File(['text,date,p_id,note_id,report_type\nnote1,2024-01-01,p1,n1,Pathology'], 'test.csv', {
      type: 'text/csv',
    })
    fireEvent.change(fileInput, { target: { files: [file] } })

    const uploadButton = screen.getByRole('button', { name: /Upload & Parse/i })
    fireEvent.click(uploadButton)

    await waitFor(() => {
      expect(screen.getByText('Parsed 2 rows')).toBeInTheDocument()
    })

    // Only 1 checkbox should be checked (diagnosis for Pathology)
    // Radiology has no saved mapping so it defaults to empty
    const checkboxes = screen.getAllByRole('checkbox') as HTMLInputElement[]
    const checkedBoxes = checkboxes.filter(cb => cb.checked)
    expect(checkedBoxes.length).toBe(1)
  })
})
