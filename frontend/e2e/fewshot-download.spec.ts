import { test, expect } from '@playwright/test'
import path from 'path'

const API_BASE = 'http://localhost:8001'

// Helper: upload a fewshot CSV via API for a given center
async function uploadFewshotsViaAPI(request: any, center: string) {
  const csvContent =
    'prompt_type,note_text,annotation\n' +
    'gender,"Patient is a 65-year-old male presenting with chest pain.","Patient\'s gender male."\n' +
    'ageatdiagnosis,"Patient is a 65-year-old male presenting with chest pain.","Age at diagnosis 65 years."\n'

  const resp = await request.post(`${API_BASE}/api/upload/fewshots?center=${center}`, {
    multipart: {
      file: {
        name: 'fewshots.csv',
        mimeType: 'text/csv',
        buffer: Buffer.from(csvContent),
      },
    },
  })
  expect(resp.ok()).toBeTruthy()
  return resp.json()
}

// Helper: delete all fewshots
async function cleanupFewshots(request: any) {
  await request.delete(`${API_BASE}/api/upload/fewshots`)
}

test.beforeEach(async ({ request }) => {
  await cleanupFewshots(request)
})

test.afterEach(async ({ request }) => {
  await cleanupFewshots(request)
})

test.describe('Fewshot Download on Upload Page', () => {
  test('download button is hidden when no fewshots exist for center', async ({ page }) => {
    await page.goto('/upload')
    // Switch to a center with no fewshot data (FAISS or simple)
    const centerSelect = page.locator('label:has-text("Center for Few-Shots") + select')
    await centerSelect.selectOption('VGR')
    await page.waitForTimeout(1500)
    await expect(page.locator('button:has-text("Download CSV")')).not.toBeVisible()
  })

  test('download button appears when FAISS fewshots exist (no simple upload needed)', async ({ page }) => {
    // INT-SARC has FAISS data on disk — no need to upload simple fewshots
    await page.goto('/upload')
    await expect(page.locator('button:has-text("Download CSV")')).toBeVisible({ timeout: 10000 })
    // Status should show as configured
    await expect(page.locator('text=properly configured')).toBeVisible()
  })

  test('download button appears when simple fewshots are uploaded', async ({ page, request }) => {
    await uploadFewshotsViaAPI(request, 'INT-SARC')

    await page.goto('/upload')
    await expect(page.locator('button:has-text("Download CSV")')).toBeVisible({ timeout: 10000 })
  })

  test('clicking download triggers a file download', async ({ page, request }) => {
    await uploadFewshotsViaAPI(request, 'INT-SARC')

    await page.goto('/upload')
    await expect(page.locator('button:has-text("Download CSV")')).toBeVisible({ timeout: 10000 })

    // Listen for the download event
    const downloadPromise = page.waitForEvent('download')
    await page.click('button:has-text("Download CSV")')
    const download = await downloadPromise

    // Verify filename
    expect(download.suggestedFilename()).toBe('fewshots_int-sarc.csv')

    // Verify content
    const filePath = await download.path()
    const fs = await import('fs')
    const content = fs.readFileSync(filePath!, 'utf-8')
    const lines = content.trim().split('\n')

    // Header + 2 data rows
    expect(lines.length).toBe(3)
    expect(lines[0].trim()).toBe('prompt_type,note_text,annotation')
    // Prompt types should NOT have center suffix
    expect(content).toContain('gender,')
    expect(content).toContain('ageatdiagnosis,')
    expect(content).not.toContain('-int-sarc')
  })

  test('download respects selected center', async ({ page, request }) => {
    // Upload fewshots for two different centers
    await uploadFewshotsViaAPI(request, 'INT-SARC')
    await uploadFewshotsViaAPI(request, 'MSCI')

    await page.goto('/upload')

    // Switch fewshot center to MSCI using the "Center for Few-Shots" select
    const fewshotCenterSelect = page.locator('label:has-text("Center for Few-Shots") + select')
    await fewshotCenterSelect.selectOption('MSCI')
    // Wait for status to reload after center change
    await page.waitForTimeout(1500)

    await expect(page.locator('button:has-text("Download CSV")')).toBeVisible({ timeout: 10000 })

    const downloadPromise = page.waitForEvent('download')
    await page.click('button:has-text("Download CSV")')
    const download = await downloadPromise

    expect(download.suggestedFilename()).toBe('fewshots_msci.csv')
  })
})
