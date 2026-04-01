import { test, expect, Page } from '@playwright/test'

const API_BASE = 'http://localhost:8001'

// Mock session data with a history note
const MOCK_SESSION_ID = 'test-history-splitting'

const HISTORY_DETECTION = {
  is_history: true,
  was_split: true,
  events_count: 4,
  detection_methods: ['date_count', 'event_markers', 'diverse_treatments'],
  date_count: 7,
  event_marker_count: 8,
  treatment_types_found: ['surgery', 'chemotherapy', 'radiotherapy'],
  events: [
    { event_text: 'Surgery performed on right breast 03/2020', event_type: 'surgery', event_date: '03/2020' },
    { event_text: 'Chemotherapy started 06/2020 with paclitaxel', event_type: 'chemotherapy', event_date: '06/2020' },
    { event_text: 'Radiotherapy completed 12/2020', event_type: 'radiotherapy', event_date: '12/2020' },
    { event_text: 'Recurrence detected in left breast 06/2021', event_type: 'recurrence', event_date: '06/2021' },
  ],
}

function makeMockSession(annotations: Record<string, any> = {}) {
  return {
    session_id: MOCK_SESSION_ID,
    name: 'History Splitting Test',
    description: 'E2E test session',
    created_at: '2026-04-01T00:00:00',
    notes: [
      {
        note_id: 'note_1',
        text: 'Anamnesis: Patient diagnosed with sarcoma in 01/2020. Underwent surgery 03/2020. Chemotherapy started 06/2020. Radiotherapy completed 12/2020. Recurrence detected 06/2021. Second surgery 09/2021.',
        p_id: 'P001',
        report_type: 'anamnesis',
        date: '2026-01-15',
      },
      {
        note_id: 'note_2',
        text: 'Pathology report: Grade 2 sarcoma. Tumor size 4.5cm.',
        p_id: 'P001',
        report_type: 'pathology',
        date: '2026-01-20',
      },
    ],
    prompt_types: ['gender', 'laterality', 'tumoursize'],
    annotations,
    report_type_mapping: {
      anamnesis: ['gender', 'laterality', 'tumoursize'],
      pathology: ['gender', 'laterality', 'tumoursize'],
    },
    evaluation_mode: 'validation',
  }
}

function makeAnnotationWithMultiValue() {
  return {
    prompt_type: 'gender',
    annotation_text: 'male',
    values: [
      { value: 'surgery 03/2020', evidence_spans: [], reasoning: 'Event 1' },
      { value: 'chemotherapy 06/2020', evidence_spans: [], reasoning: 'Event 2' },
      { value: 'surgery 09/2021', evidence_spans: [], reasoning: 'Event 3' },
    ],
    is_negated: false,
    status: 'success',
    multi_value_info: {
      was_split: true,
      total_events_detected: 4,
      unique_values_extracted: 3,
      split_method: 'llm',
    },
  }
}

function makeAnnotation(promptType: string) {
  return {
    prompt_type: promptType,
    annotation_text: 'test value',
    values: [{ value: 'test value', evidence_spans: [], reasoning: '' }],
    is_negated: false,
    status: 'success',
  }
}

// Build SSE body for batch/stream with history detection on first progress event
function buildBatchSSE(opts: { withHistory: boolean; withMultiValue: boolean }): string {
  const events: string[] = []

  events.push(`event: started\ndata: ${JSON.stringify({ total_notes: 1, total_prompts: 3 })}\n\n`)

  const prog1: Record<string, any> = {
    completed: 1, total: 3, note_id: 'note_1', prompt_type: 'gender', percentage: 33,
  }
  if (opts.withHistory) {
    prog1.history_detection = HISTORY_DETECTION
  }
  events.push(`event: progress\ndata: ${JSON.stringify(prog1)}\n\n`)
  events.push(`event: progress\ndata: ${JSON.stringify({
    completed: 2, total: 3, note_id: 'note_1', prompt_type: 'laterality', percentage: 66,
  })}\n\n`)
  events.push(`event: progress\ndata: ${JSON.stringify({
    completed: 3, total: 3, note_id: 'note_1', prompt_type: 'tumoursize', percentage: 100,
  })}\n\n`)

  const annotations = [
    opts.withMultiValue ? makeAnnotationWithMultiValue() : makeAnnotation('gender'),
    makeAnnotation('laterality'),
    makeAnnotation('tumoursize'),
  ]

  const completeData = {
    results: [{
      note_id: 'note_1',
      note_text: 'test',
      annotations,
      processing_time_seconds: 5.2,
      timing_breakdown: { llm_call: 4.0, prompt_building: 0.5, note_count: 1, prompt_count: 3 },
      history_detection: opts.withHistory ? HISTORY_DETECTION : undefined,
    }],
    total_time_seconds: 5.2,
    timing_breakdown: { llm_call: 4.0, prompt_building: 0.5, note_count: 1, prompt_count: 3, sum_llm_call: 4.0 },
  }
  events.push(`event: complete\ndata: ${JSON.stringify(completeData)}\n\n`)

  return events.join('')
}

// Build SSE body for sequential/stream with history detection on note_1
function buildSequentialSSE(): string {
  const events: string[] = []

  events.push(`event: started\ndata: ${JSON.stringify({
    session_id: MOCK_SESSION_ID, total_notes: 2, notes_to_process: 2, skipped: 0,
  })}\n\n`)

  events.push(`event: progress\ndata: ${JSON.stringify({
    note_id: 'note_1', status: 'success', annotations_count: 3,
    completed: 1, total: 2, percentage: 50, processing_time_seconds: 5.0,
    history_detection: HISTORY_DETECTION,
  })}\n\n`)

  events.push(`event: progress\ndata: ${JSON.stringify({
    note_id: 'note_2', status: 'success', annotations_count: 3,
    completed: 2, total: 2, percentage: 100, processing_time_seconds: 2.0,
  })}\n\n`)

  const completeData = {
    session_id: MOCK_SESSION_ID,
    total_notes: 2, processed: 2, skipped: 0, errors: 0,
    results: [
      { note_id: 'note_1', status: 'success', annotations_count: 3, processing_time_seconds: 5.0 },
      { note_id: 'note_2', status: 'success', annotations_count: 3, processing_time_seconds: 2.0 },
    ],
    total_time_seconds: 7.0,
    timing_summary: { total_processing_time: 7.0, avg_per_note: 3.5, min_per_note: 2.0, max_per_note: 5.0 },
  }
  events.push(`event: complete\ndata: ${JSON.stringify(completeData)}\n\n`)

  return events.join('')
}

// Setup route mocks
async function setupMocks(page: Page, opts: {
  withHistory: boolean
  batch?: boolean
  postProcessAnnotations?: Record<string, any>
}) {
  const baseSession = makeMockSession()

  // Session with annotations (returned after processing completes)
  const sessionWithAnnotations = makeMockSession(opts.postProcessAnnotations || {})

  let getCount = 0
  await page.route(`${API_BASE}/api/sessions/${MOCK_SESSION_ID}`, async (route) => {
    if (route.request().method() === 'GET') {
      getCount++
      // First GET: empty session. Subsequent GETs: session with annotations (simulates refresh after processing)
      const data = getCount <= 1 ? baseSession : sessionWithAnnotations
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(data) })
    } else if (route.request().method() === 'PUT') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(sessionWithAnnotations) })
    } else {
      await route.continue()
    }
  })

  // Mock prompts (use ** to match /prompts/centers as well)
  await page.route(`${API_BASE}/api/prompts**`, async (route) => {
    if (route.request().url().includes('/centers')) {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(['INT-SARC']) })
    } else {
      await route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify([
          { prompt_type: 'gender', description: 'Gender', template: 'What is the gender?' },
          { prompt_type: 'laterality', description: 'Laterality', template: 'What is the laterality?' },
          { prompt_type: 'tumoursize', description: 'Tumour size', template: 'What is the tumour size?' },
        ]),
      })
    }
  })

  // Mock server status
  await page.route(`${API_BASE}/api/server/status`, async (route) => {
    await route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ status: 'available', model: 'test-model' }),
    })
  })

  if (opts.batch) {
    await page.route(`${API_BASE}/api/annotate/sequential/stream*`, async (route) => {
      await route.fulfill({
        status: 200,
        headers: { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache' },
        body: buildSequentialSSE(),
      })
    })
  } else {
    await page.route(`${API_BASE}/api/annotate/batch/stream*`, async (route) => {
      await route.fulfill({
        status: 200,
        headers: { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache' },
        body: buildBatchSSE({ withHistory: opts.withHistory, withMultiValue: opts.withHistory }),
      })
    })
  }
}


test.describe('History Note Splitting Feedback', () => {

  test('shows multi-value badge on annotation after processing a history note', async ({ page }) => {
    // After processing, the AnnotationViewer should show "3 events extracted" badge
    // for annotations with multi_value_info
    const postAnnotations = {
      note_1: {
        gender: {
          note_id: 'note_1',
          prompt_type: 'gender',
          annotation_text: 'surgery 03/2020',
          values: [
            { value: 'surgery 03/2020', evidence_spans: [] },
            { value: 'chemotherapy 06/2020', evidence_spans: [] },
            { value: 'surgery 09/2021', evidence_spans: [] },
          ],
          edited: false,
          is_negated: false,
          status: 'success',
          multi_value_info: {
            was_split: true,
            total_events_detected: 4,
            unique_values_extracted: 3,
            split_method: 'llm',
          },
        },
        laterality: {
          note_id: 'note_1',
          prompt_type: 'laterality',
          annotation_text: 'left',
          values: [{ value: 'left', evidence_spans: [] }],
          edited: false,
          is_negated: false,
          status: 'success',
        },
        tumoursize: {
          note_id: 'note_1',
          prompt_type: 'tumoursize',
          annotation_text: '4.5cm',
          values: [{ value: '4.5cm', evidence_spans: [] }],
          edited: false,
          is_negated: false,
          status: 'success',
        },
      },
    }

    await setupMocks(page, { withHistory: true, postProcessAnnotations: postAnnotations })
    await page.goto(`/annotate/${MOCK_SESSION_ID}`)
    await page.waitForSelector('text=Clinical Note')

    // Click Process Note
    await page.click('button:has-text("Process Note")')

    // Wait for processing to complete and annotations to render
    // The session refresh after processing returns annotations with multi_value_info
    const badge = page.locator('text=3 events extracted')
    await expect(badge).toBeVisible({ timeout: 15000 })
  })

  test('no multi-value badge when note is not a history note', async ({ page }) => {
    const postAnnotations = {
      note_1: {
        gender: {
          note_id: 'note_1',
          prompt_type: 'gender',
          annotation_text: 'male',
          values: [{ value: 'male', evidence_spans: [] }],
          edited: false,
          is_negated: false,
          status: 'success',
          // No multi_value_info
        },
      },
    }

    await setupMocks(page, { withHistory: false, postProcessAnnotations: postAnnotations })
    await page.goto(`/annotate/${MOCK_SESSION_ID}`)
    await page.waitForSelector('text=Clinical Note')

    // Click Process Note
    await page.click('button:has-text("Process Note")')

    // Wait for annotations to appear (look for the Parsed badge which renders for processed annotations)
    await expect(page.locator('text=Parsed').first()).toBeVisible({ timeout: 15000 })

    // Verify no multi-value badge
    await expect(page.locator('text=events extracted')).not.toBeVisible()
  })

  test('shows history summary in batch completion report', async ({ page }) => {
    // After batch processing, the completion report shows history note splitting summary
    const postAnnotations = {
      note_1: {
        gender: {
          note_id: 'note_1', prompt_type: 'gender', annotation_text: 'test',
          values: [{ value: 'test', evidence_spans: [] }],
          edited: false, is_negated: false, status: 'success',
          multi_value_info: { was_split: true, total_events_detected: 4, unique_values_extracted: 3, split_method: 'llm' },
        },
      },
      note_2: {
        gender: {
          note_id: 'note_2', prompt_type: 'gender', annotation_text: 'test',
          values: [{ value: 'test', evidence_spans: [] }],
          edited: false, is_negated: false, status: 'success',
        },
      },
    }

    await setupMocks(page, { withHistory: true, batch: true, postProcessAnnotations: postAnnotations })
    await page.goto(`/annotate/${MOCK_SESSION_ID}`)
    await page.waitForSelector('text=Batch Processing')

    // Click Process All Notes
    await page.click('button:has-text("Process All Notes")')

    // Wait for completion report
    await page.waitForSelector('text=Processing Complete', { timeout: 15000 })

    // Assert: history summary appears in completion report
    const report = page.locator('[data-testid="batch-history-report"]')
    await expect(report).toBeVisible()
    await expect(report).toContainText('History notes:')
    await expect(report).toContainText('4 events')
  })

  test('multi-value badge shows correct event count from multi_value_info', async ({ page }) => {
    // Directly load a session that already has annotations with multi_value_info
    // This tests the AnnotationViewer badge rendering without processing
    const sessionWithAnnotations = makeMockSession({
      note_1: {
        gender: {
          note_id: 'note_1',
          prompt_type: 'gender',
          annotation_text: 'surgery 03/2020',
          values: [
            { value: 'surgery 03/2020', evidence_spans: [] },
            { value: 'chemotherapy 06/2020', evidence_spans: [] },
          ],
          edited: false,
          is_negated: false,
          status: 'success',
          multi_value_info: {
            was_split: true,
            total_events_detected: 3,
            unique_values_extracted: 2,
            split_method: 'llm',
          },
        },
      },
    })

    await page.route(`${API_BASE}/api/sessions/${MOCK_SESSION_ID}`, async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(sessionWithAnnotations) })
    })
    await page.route(`${API_BASE}/api/prompts**`, async (route) => {
      if (route.request().url().includes('/centers')) {
        await route.fulfill({
          status: 200, contentType: 'application/json',
          body: JSON.stringify(['INT-SARC']),
        })
      } else {
        await route.fulfill({
          status: 200, contentType: 'application/json',
          body: JSON.stringify([{ prompt_type: 'gender', description: 'Gender', template: 'What?' }]),
        })
      }
    })
    await page.route(`${API_BASE}/api/server/status`, async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'available' }) })
    })

    await page.goto(`/annotate/${MOCK_SESSION_ID}`)
    await page.waitForSelector('text=Clinical Note')

    // The badge should show immediately since the session already has annotations
    const badge = page.locator('text=2 events extracted')
    await expect(badge).toBeVisible({ timeout: 10000 })
  })
})
