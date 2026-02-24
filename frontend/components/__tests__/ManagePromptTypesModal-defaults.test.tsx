import { render, screen, cleanup } from '@testing-library/react'
import { vi, describe, it, expect, beforeEach, afterEach } from 'vitest'
import ManagePromptTypesModal from '../ManagePromptTypesModal'
import type { SessionData, PromptInfo } from '@/lib/api'

vi.mock('@/lib/api', () => ({
  presetsApi: {
    list: vi.fn().mockResolvedValue([]),
    create: vi.fn(),
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
  report_type_mapping: {},
  ...overrides,
})

const makePrompts = (): PromptInfo[] => [
  { prompt_type: 'gender-int', description: 'Gender', system_prompt: '', user_prompt: '', center: 'test' },
  { prompt_type: 'diagnosis', description: 'Diagnosis', system_prompt: '', user_prompt: '', center: 'test' },
  { prompt_type: 'staging', description: 'Staging', system_prompt: '', user_prompt: '', center: 'test' },
]

describe('ManagePromptTypesModal – default empty selection', () => {
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
  })

  afterEach(() => {
    cleanup()
  })

  it('initializes with empty arrays when no report_type_mapping exists for report types', () => {
    // Session has no report_type_mapping entries
    render(<ManagePromptTypesModal {...defaultProps} />)

    // All chips should be deselected (gray background, not blue)
    const genderChips = screen.getAllByText('gender-int')
    genderChips.forEach((chip) => {
      expect(chip.className).toContain('bg-gray-50')
      expect(chip.className).not.toContain('bg-blue-100')
    })

    const diagnosisChips = screen.getAllByText('diagnosis')
    diagnosisChips.forEach((chip) => {
      expect(chip.className).toContain('bg-gray-50')
      expect(chip.className).not.toContain('bg-blue-100')
    })
  })

  it('uses existing mapping when report_type_mapping has entries', () => {
    const session = makeSession({
      report_type_mapping: {
        Pathology: ['diagnosis'],
        Radiology: ['staging'],
      },
    })

    render(
      <ManagePromptTypesModal
        {...defaultProps}
        session={session}
      />
    )

    // Pathology section: only diagnosis should be selected
    const pathologySection = screen.getByText('Pathology').closest('div.border')!
    const pathChips = pathologySection.querySelectorAll('button')
    const pathDiagnosis = Array.from(pathChips).find(c => c.textContent === 'diagnosis')!
    const pathGender = Array.from(pathChips).find(c => c.textContent === 'gender-int')!

    expect(pathDiagnosis.className).toContain('bg-blue-100')
    expect(pathGender.className).toContain('bg-gray-50')

    // Radiology section: only staging should be selected
    const radiologySection = screen.getByText('Radiology').closest('div.border')!
    const radChips = radiologySection.querySelectorAll('button')
    const radStaging = Array.from(radChips).find(c => c.textContent === 'staging')!
    const radGender = Array.from(radChips).find(c => c.textContent === 'gender-int')!

    expect(radStaging.className).toContain('bg-blue-100')
    expect(radGender.className).toContain('bg-gray-50')
  })

  it('does not fall back to session.prompt_types when mapping is missing', () => {
    // Session has prompt_types but no report_type_mapping
    const session = makeSession({
      prompt_types: ['gender-int', 'diagnosis', 'staging'],
      report_type_mapping: {},
    })

    render(
      <ManagePromptTypesModal
        {...defaultProps}
        session={session}
      />
    )

    // No chips should be selected despite session having prompt_types
    const allChipTexts = ['gender-int', 'diagnosis', 'staging']
    for (const text of allChipTexts) {
      const chips = screen.getAllByText(text)
      chips.forEach((chip) => {
        expect(chip.className).not.toContain('bg-blue-100')
      })
    }
  })
})
