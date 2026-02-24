import { render, screen, waitFor, fireEvent, cleanup } from '@testing-library/react'
import { vi, describe, it, expect, beforeEach, afterEach } from 'vitest'
import ManagePromptTypesModal from '../ManagePromptTypesModal'
import type { SessionData, PromptInfo } from '@/lib/api'

const mockPresetsApiList = vi.fn()
const mockPresetsApiCreate = vi.fn()

vi.mock('@/lib/api', () => ({
  presetsApi: {
    list: (...args: unknown[]) => mockPresetsApiList(...args),
    create: (...args: unknown[]) => mockPresetsApiCreate(...args),
  },
}))

const makeSession = (overrides: Partial<SessionData> = {}): SessionData => ({
  session_id: 'sess-1',
  name: 'Test Session',
  created_at: '2024-01-01T00:00:00Z',
  updated_at: '2024-01-01T00:00:00Z',
  notes: [
    { text: 'note1', date: '2024-01-01', p_id: 'p1', note_id: 'n1', report_type: 'Pathology' },
    { text: 'note2', date: '2024-01-02', p_id: 'p2', note_id: 'n2', report_type: 'Radiology' },
  ],
  annotations: {},
  prompt_types: ['gender-int', 'diagnosis', 'staging'],
  report_type_mapping: {
    Pathology: ['gender-int', 'diagnosis', 'staging'],
    Radiology: ['gender-int', 'diagnosis', 'staging'],
  },
  ...overrides,
})

const makePrompts = (): PromptInfo[] => [
  { prompt_type: 'gender-int', description: 'Gender', system_prompt: '', user_prompt: '', center: 'test' },
  { prompt_type: 'diagnosis', description: 'Diagnosis', system_prompt: '', user_prompt: '', center: 'test' },
  { prompt_type: 'staging', description: 'Staging', system_prompt: '', user_prompt: '', center: 'test' },
]

const makePreset = (mapping: Record<string, string[]>) => ({
  id: 'preset-1',
  name: 'Test Preset',
  center: 'test',
  report_type_mapping: mapping,
  created_at: '2024-01-01T00:00:00Z',
  updated_at: '2024-01-01T00:00:00Z',
})

describe('ManagePromptTypesModal', () => {
  const defaultProps = {
    session: makeSession(),
    availablePrompts: makePrompts(),
    onClose: vi.fn(),
    onSave: vi.fn().mockResolvedValue(undefined),
    error: null,
    center: 'test',
  }

  beforeEach(() => {
    vi.clearAllMocks()
    mockPresetsApiList.mockResolvedValue([])
  })

  afterEach(() => {
    cleanup()
  })

  it('renders chips for all prompt types per report type', () => {
    render(<ManagePromptTypesModal {...defaultProps} />)
    // Each report type section should show all 3 prompt type chips
    const genderButtons = screen.getAllByText('gender-int')
    expect(genderButtons.length).toBe(2) // One per report type
  })

  it('initially shows all chips as selected (blue) based on session mapping', () => {
    render(<ManagePromptTypesModal {...defaultProps} />)
    // All chips should have the selected class
    const chips = screen.getAllByText('gender-int')
    chips.forEach((chip) => {
      expect(chip.className).toContain('bg-blue-100')
    })
  })

  it('updates chips when a preset is loaded', async () => {
    // Preset that only selects "diagnosis" for Pathology and "staging" for Radiology
    const preset = makePreset({
      Pathology: ['diagnosis'],
      Radiology: ['staging'],
    })
    mockPresetsApiList.mockResolvedValue([preset])

    render(<ManagePromptTypesModal {...defaultProps} />)

    // Wait for presets to load in the PresetSelector
    await waitFor(() => {
      expect(screen.getByText(/Test Preset/)).toBeInTheDocument()
    })

    // Select and load the preset
    const select = screen.getByRole('combobox')
    fireEvent.change(select, { target: { value: 'preset-1' } })
    fireEvent.click(screen.getByRole('button', { name: 'Load' }))

    // Wait for the success message
    await waitFor(() => {
      expect(screen.getByText(/Loaded preset/)).toBeInTheDocument()
    })

    // Now verify the chips updated:
    // Pathology section should show "diagnosis" as selected, "gender-int" and "staging" as deselected
    const pathologySection = screen.getByText('Pathology').closest('div.border')!
    const pathologyChips = pathologySection.querySelectorAll('button')

    // Find the chips by text content
    const pathologyGender = Array.from(pathologyChips).find(c => c.textContent === 'gender-int')!
    const pathologyDiagnosis = Array.from(pathologyChips).find(c => c.textContent === 'diagnosis')!
    const pathologyStaging = Array.from(pathologyChips).find(c => c.textContent === 'staging')!

    expect(pathologyGender.className).toContain('bg-gray-50') // deselected
    expect(pathologyDiagnosis.className).toContain('bg-blue-100') // selected
    expect(pathologyStaging.className).toContain('bg-gray-50') // deselected

    // Radiology section should show "staging" as selected, others deselected
    const radiologySection = screen.getByText('Radiology').closest('div.border')!
    const radiologyChips = radiologySection.querySelectorAll('button')

    const radiologyGender = Array.from(radiologyChips).find(c => c.textContent === 'gender-int')!
    const radiologyDiagnosis = Array.from(radiologyChips).find(c => c.textContent === 'diagnosis')!
    const radiologyStaging = Array.from(radiologyChips).find(c => c.textContent === 'staging')!

    expect(radiologyGender.className).toContain('bg-gray-50') // deselected
    expect(radiologyDiagnosis.className).toContain('bg-gray-50') // deselected
    expect(radiologyStaging.className).toContain('bg-blue-100') // selected
  })

  it('preserves unmatched report types when loading a partial preset', async () => {
    // Preset only has mapping for Pathology, not Radiology
    const preset = makePreset({
      Pathology: ['diagnosis'],
    })
    mockPresetsApiList.mockResolvedValue([preset])

    render(<ManagePromptTypesModal {...defaultProps} />)

    await waitFor(() => {
      expect(screen.getByText(/Test Preset/)).toBeInTheDocument()
    })

    const select = screen.getByRole('combobox')
    fireEvent.change(select, { target: { value: 'preset-1' } })
    fireEvent.click(screen.getByRole('button', { name: 'Load' }))

    await waitFor(() => {
      expect(screen.getByText(/Skipped: Radiology/)).toBeInTheDocument()
    })

    // Pathology should be updated to only "diagnosis"
    const pathologySection = screen.getByText('Pathology').closest('div.border')!
    const pathDiagnosis = Array.from(pathologySection.querySelectorAll('button')).find(c => c.textContent === 'diagnosis')!
    expect(pathDiagnosis.className).toContain('bg-blue-100')

    // Radiology should still have all original selections (unchanged)
    const radiologySection = screen.getByText('Radiology').closest('div.border')!
    const radChips = radiologySection.querySelectorAll('button')
    Array.from(radChips).forEach((chip) => {
      if (['gender-int', 'diagnosis', 'staging'].includes(chip.textContent || '')) {
        expect(chip.className).toContain('bg-blue-100') // still selected
      }
    })
  })

  it('enables Save Changes button after loading a preset that differs from current state', async () => {
    const preset = makePreset({
      Pathology: ['diagnosis'],
      Radiology: ['staging'],
    })
    mockPresetsApiList.mockResolvedValue([preset])

    render(<ManagePromptTypesModal {...defaultProps} />)

    // Initially Save Changes should be disabled (no changes)
    const saveButton = screen.getByRole('button', { name: 'Save Changes' })
    expect(saveButton).toBeDisabled()

    await waitFor(() => {
      expect(screen.getByText(/Test Preset/)).toBeInTheDocument()
    })

    const select = screen.getByRole('combobox')
    fireEvent.change(select, { target: { value: 'preset-1' } })
    fireEvent.click(screen.getByRole('button', { name: 'Load' }))

    await waitFor(() => {
      expect(screen.getByText(/Loaded preset/)).toBeInTheDocument()
    })

    // Now Save Changes should be enabled
    expect(saveButton).not.toBeDisabled()
  })
})
