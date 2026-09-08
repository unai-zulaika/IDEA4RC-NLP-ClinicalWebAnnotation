/**
 * The retry interceptor must not replay non-idempotent requests.
 *
 * A 502/503/504 does not mean the server did no work — a gateway timeout on a
 * still-running batch is the common case. Replaying a POST created a second
 * session, or launched a second annotation run over the same notes.
 *
 * Uses axios's own adapter hook rather than a mock library, so this needs no
 * extra dependency.
 */
import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import type { AxiosAdapter, AxiosRequestConfig } from 'axios'
import api from '../api'

interface Call { method: string; url: string }

const originalAdapter = api.defaults.adapter
let calls: Call[] = []

/** Adapter that fails every request with `status`, recording each attempt. */
function failingAdapter(status: number): AxiosAdapter {
  return (config: AxiosRequestConfig) => {
    calls.push({ method: (config.method || 'get').toLowerCase(), url: config.url || '' })
    return Promise.reject(
      Object.assign(new Error(`Request failed with status code ${status}`), {
        config,
        response: { status, data: {}, statusText: '', headers: {}, config },
        isAxiosError: true,
      }),
    )
  }
}

/** Adapter that fails the first `failures` attempts, then succeeds. */
function flakyAdapter(status: number, failures: number): AxiosAdapter {
  let seen = 0
  return (config: AxiosRequestConfig) => {
    calls.push({ method: (config.method || 'get').toLowerCase(), url: config.url || '' })
    seen += 1
    if (seen <= failures) {
      return Promise.reject(
        Object.assign(new Error(`Request failed with status code ${status}`), {
          config,
          response: { status, data: {}, statusText: '', headers: {}, config },
          isAxiosError: true,
        }),
      )
    }
    return Promise.resolve({
      data: [], status: 200, statusText: 'OK', headers: {}, config,
    } as any)
  }
}

beforeEach(() => { calls = [] })
afterEach(() => { api.defaults.adapter = originalAdapter })

describe('retry interceptor', () => {
  it('retries an idempotent GET on 503', async () => {
    api.defaults.adapter = flakyAdapter(503, 1)
    const res = await api.get('/api/sessions')
    expect(res.status).toBe(200)
    expect(calls.filter((c) => c.method === 'get')).toHaveLength(2)
  })

  it('does NOT retry a POST on 504 — the run may still be in flight', async () => {
    api.defaults.adapter = failingAdapter(504)
    await expect(api.post('/api/sessions', {})).rejects.toBeDefined()
    expect(calls.filter((c) => c.method === 'post')).toHaveLength(1)
  })

  it('does NOT retry a POST on 502', async () => {
    api.defaults.adapter = failingAdapter(502)
    await expect(api.post('/api/annotate/batch', {})).rejects.toBeDefined()
    expect(calls.filter((c) => c.method === 'post')).toHaveLength(1)
  })

  it('gives up after 2 retries', async () => {
    api.defaults.adapter = failingAdapter(503)
    await expect(api.get('/api/server/status')).rejects.toBeDefined()
    expect(calls.filter((c) => c.method === 'get')).toHaveLength(3) // original + 2
  })

  it('does not retry a 404', async () => {
    api.defaults.adapter = failingAdapter(404)
    await expect(api.get('/api/sessions/nope')).rejects.toBeDefined()
    expect(calls.filter((c) => c.method === 'get')).toHaveLength(1)
  })

  it('still retries an idempotent DELETE on 503', async () => {
    api.defaults.adapter = flakyAdapter(503, 1)
    await api.delete('/api/sessions/abc')
    expect(calls.filter((c) => c.method === 'delete')).toHaveLength(2)
  })
})
