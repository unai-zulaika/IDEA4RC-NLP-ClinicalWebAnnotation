import { render, screen, waitFor, fireEvent, cleanup, within } from '@testing-library/react'
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

// Mock useDefaultCenter to avoid localStorage issues in tests
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

const makePreset = (mapping: Record<string, string[]>) => ({
  id: 'preset-1',
  name: 'Test Preset',
  center: 'center-a',
  report_type_mapping: mapping,
  created_at: '2024-01-01T00:00:00Z',
  updated_at: '2024-01-01T00:00:00Z',
})

async function setupUploadedState() {
  render(<UploadPage />)

  // Wait for centers and prompts to load
  await waitFor(() => {
    expect(mockPromptsList).toHaveBeenCalled()
  })

  // Simulate file selection and upload — the label and input aren't associated via htmlFor,
  // so query by the accept attribute on the second file input (first is few-shot)
  const fileInputs = document.querySelectorAll('input[type="file"][accept=".csv"]')
  const fileInput = fileInputs[1] as HTMLInputElement // second file input is the CSV upload
  const file = new File(['text,date,p_id,note_id,report_type\nnote1,2024-01-01,p1,n1,Pathology'], 'test.csv', {
    type: 'text/csv',
  })
  fireEvent.change(fileInput, { target: { files: [file] } })

  const uploadButton = screen.getByRole('button', { name: /Upload & Parse/i })
  fireEvent.click(uploadButton)

  // Wait for upload result to render
  await waitFor(() => {
    expect(screen.getByText('Parsed 2 rows')).toBeInTheDocument()
  })
}

describe('UploadPage – preset loading updates checkboxes', () => {
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

  it('checkboxes update after loading a preset', async () => {
    // Preset: Pathology gets only "diagnosis", Radiology gets only "staging"
    const preset = makePreset({
      Pathology: ['diagnosis'],
      Radiology: ['staging'],
    })
    mockPresetsApiList.mockResolvedValue([preset])

    await setupUploadedState()

    // Wait for presets to load in PresetSelector
    await waitFor(() => {
      expect(screen.getByText(/Test Preset/)).toBeInTheDocument()
    })

    // No checkboxes should be initially checked (default: no prompts selected)
    const checkboxes = screen.getAllByRole('checkbox') as HTMLInputElement[]
    const initiallyChecked = checkboxes.filter(cb => cb.checked)
    expect(initiallyChecked.length).toBe(0)

    // Load the preset
    // The PresetSelector's combobox — find the preset container (border div)
    const presetContainer = screen.getByText('Annotation Presets').closest('.border')!
    const select = within(presetContainer as HTMLElement).getByRole('combobox')
    fireEvent.change(select, { target: { value: 'preset-1' } })
    fireEvent.click(within(presetContainer as HTMLElement).getByRole('button', { name: 'Load' }))

    await waitFor(() => {
      expect(screen.getByText(/Loaded preset/)).toBeInTheDocument()
    })

    // After loading: only 2 checkboxes should be checked (diagnosis for Pathology, staging for Radiology)
    const updatedCheckboxes = screen.getAllByRole('checkbox') as HTMLInputElement[]
    const checkedAfterLoad = updatedCheckboxes.filter(cb => cb.checked)
    expect(checkedAfterLoad.length).toBe(2)
  })

  it('partial preset only updates matching report types, preserves others', async () => {
    // Preset only covers Pathology
    const preset = makePreset({
      Pathology: ['diagnosis'],
    })
    mockPresetsApiList.mockResolvedValue([preset])

    await setupUploadedState()

    await waitFor(() => {
      expect(screen.getByText(/Test Preset/)).toBeInTheDocument()
    })

    // The PresetSelector's combobox — find the preset container (border div)
    const presetContainer = screen.getByText('Annotation Presets').closest('.border')!
    const select = within(presetContainer as HTMLElement).getByRole('combobox')
    fireEvent.change(select, { target: { value: 'preset-1' } })
    fireEvent.click(within(presetContainer as HTMLElement).getByRole('button', { name: 'Load' }))

    await waitFor(() => {
      expect(screen.getByText(/Skipped: Radiology/)).toBeInTheDocument()
    })

    // Pathology should have 1 checked (diagnosis), Radiology should still have 0 checked (was empty default)
    const updatedCheckboxes = screen.getAllByRole('checkbox') as HTMLInputElement[]
    const checkedAfterLoad = updatedCheckboxes.filter(cb => cb.checked)
    expect(checkedAfterLoad.length).toBe(1) // 1 (Pathology) + 0 (Radiology unchanged from empty default)
  })
})
