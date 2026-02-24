import { render, screen, waitFor, fireEvent, cleanup } from '@testing-library/react'
import { vi, describe, it, expect, beforeEach, afterEach } from 'vitest'
import PresetSelector from '../PresetSelector'

const mockList = vi.fn()
const mockCreate = vi.fn()

vi.mock('@/lib/api', () => ({
  presetsApi: {
    list: (...args: unknown[]) => mockList(...args),
    create: (...args: unknown[]) => mockCreate(...args),
  },
}))

const makePreset = (overrides: Record<string, unknown> = {}) => ({
  id: 'preset-1',
  name: 'Test Preset',
  center: 'center-a',
  report_type_mapping: { TypeA: ['field1'], TypeB: ['field2'] },
  created_at: '2024-01-01T00:00:00Z',
  updated_at: '2024-01-01T00:00:00Z',
  ...overrides,
})

describe('PresetSelector', () => {
  const defaultProps = {
    center: 'center-a',
    currentMapping: {},
    onLoadPreset: vi.fn(),
    reportTypes: ['TypeA', 'TypeB'],
  }

  beforeEach(() => {
    vi.clearAllMocks()
    mockList.mockResolvedValue([])
  })

  afterEach(() => {
    cleanup()
  })

  it('calls presetsApi.list on mount with center', async () => {
    render(<PresetSelector {...defaultProps} />)
    await waitFor(() => {
      expect(mockList).toHaveBeenCalledWith('center-a')
    })
  })

  it('does not call presetsApi.list when center is empty', async () => {
    render(<PresetSelector {...defaultProps} center="" />)
    // Give it a tick to potentially fire
    await new Promise((r) => setTimeout(r, 50))
    expect(mockList).not.toHaveBeenCalled()
  })

  it('renders presets in dropdown with match counts', async () => {
    const preset = makePreset()
    mockList.mockResolvedValue([preset])
    render(<PresetSelector {...defaultProps} />)

    await waitFor(() => {
      expect(screen.getByText('Test Preset (2/2 types match)')).toBeInTheDocument()
    })
  })

  it('shows partial match count when only some types match', async () => {
    const preset = makePreset({
      report_type_mapping: { TypeA: ['field1'], TypeC: ['field3'] },
    })
    mockList.mockResolvedValue([preset])
    render(<PresetSelector {...defaultProps} reportTypes={['TypeA', 'TypeB']} />)

    await waitFor(() => {
      expect(screen.getByText('Test Preset (1/2 types match)')).toBeInTheDocument()
    })
  })

  it('shows warning when no report types match and does not call onLoadPreset', async () => {
    const preset = makePreset({
      report_type_mapping: { TypeX: ['field1'], TypeY: ['field2'] },
    })
    mockList.mockResolvedValue([preset])
    const onLoadPreset = vi.fn()
    render(
      <PresetSelector {...defaultProps} onLoadPreset={onLoadPreset} reportTypes={['TypeA', 'TypeB']} />
    )

    // Wait for presets to load
    await waitFor(() => {
      expect(screen.getByText('Test Preset (0/2 types match)')).toBeInTheDocument()
    })

    // Select the preset and click Load
    const select = screen.getByRole('combobox')
    fireEvent.change(select, { target: { value: 'preset-1' } })
    fireEvent.click(screen.getByRole('button', { name: 'Load' }))

    await waitFor(() => {
      expect(screen.getByText(/None of this preset's report types match/)).toBeInTheDocument()
    })
    expect(onLoadPreset).not.toHaveBeenCalled()
  })

  it('loads partial matches and shows info about skipped types', async () => {
    const preset = makePreset({
      report_type_mapping: { TypeA: ['field1'], TypeC: ['field3'] },
    })
    mockList.mockResolvedValue([preset])
    const onLoadPreset = vi.fn()
    render(
      <PresetSelector {...defaultProps} onLoadPreset={onLoadPreset} reportTypes={['TypeA', 'TypeB']} />
    )

    await waitFor(() => {
      expect(screen.getByText('Test Preset (1/2 types match)')).toBeInTheDocument()
    })

    const select = screen.getByRole('combobox')
    fireEvent.change(select, { target: { value: 'preset-1' } })
    fireEvent.click(screen.getByRole('button', { name: 'Load' }))

    await waitFor(() => {
      expect(screen.getByText(/Skipped: TypeB/)).toBeInTheDocument()
    })
    expect(onLoadPreset).toHaveBeenCalledWith({ TypeA: ['field1'] })
  })

  it('loads full match with success message', async () => {
    const preset = makePreset()
    mockList.mockResolvedValue([preset])
    const onLoadPreset = vi.fn()
    render(
      <PresetSelector {...defaultProps} onLoadPreset={onLoadPreset} />
    )

    await waitFor(() => {
      expect(screen.getByText('Test Preset (2/2 types match)')).toBeInTheDocument()
    })

    const select = screen.getByRole('combobox')
    fireEvent.change(select, { target: { value: 'preset-1' } })
    fireEvent.click(screen.getByRole('button', { name: 'Load' }))

    await waitFor(() => {
      expect(screen.getByText('Loaded preset "Test Preset"')).toBeInTheDocument()
    })
    expect(onLoadPreset).toHaveBeenCalledWith({ TypeA: ['field1'], TypeB: ['field2'] })
  })
})
