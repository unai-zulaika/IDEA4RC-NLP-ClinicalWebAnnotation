import { test, expect } from '@playwright/test'

const API_BASE = 'http://localhost:8001'

// Helper to create a preset via API
async function createPresetViaAPI(request: any) {
  const resp = await request.post(`${API_BASE}/api/presets`, {
    data: {
      name: 'Test Preset',
      center: 'INT',
      description: 'E2E test preset',
      report_type_mapping: {
        pathology: ['histology-int', 'grading-int'],
        radiology: ['imaging-int'],
      },
    },
  })
  expect(resp.ok()).toBeTruthy()
  return resp.json()
}

// Helper to delete all presets (cleanup)
async function cleanupPresets(request: any) {
  const resp = await request.get(`${API_BASE}/api/presets`)
  const presets = await resp.json()
  for (const preset of presets) {
    await request.delete(`${API_BASE}/api/presets/${preset.id}`)
  }
}

test.beforeEach(async ({ request }) => {
  await cleanupPresets(request)
})

test.afterEach(async ({ request }) => {
  await cleanupPresets(request)
})

test.describe('Presets Page', () => {
  test('create a preset from the presets page', async ({ page }) => {
    await page.goto('/presets')
    await page.click('text=+ Create Preset')

    await page.fill('input[placeholder="e.g. Breast Cancer Standard"]', 'My New Preset')
    await page.fill(
      'input[placeholder="Standard mapping for breast cancer reports"]',
      'Test description'
    )

    // Add a report type
    await page.fill(
      'input[placeholder="Add report type (e.g. pathology, radiology)"]',
      'pathology'
    )
    await page.click('button:has-text("Add")')

    // Create the preset
    await page.click('button:has-text("Create Preset")')

    // Verify it appears in the list
    await expect(page.locator('text=My New Preset')).toBeVisible()
    await expect(page.locator('text=Test description')).toBeVisible()
  })

  test('delete a preset', async ({ page, request }) => {
    const preset = await createPresetViaAPI(request)

    await page.goto('/presets')
    await expect(page.locator('text=Test Preset')).toBeVisible()

    // Accept the confirmation dialog
    page.on('dialog', (dialog) => dialog.accept())
    await page.click('button:has-text("Delete")')

    // Verify it's removed
    await expect(page.locator('text=Test Preset')).not.toBeVisible()
  })
})
