import { FETCH_TIMEOUT_MS, resolveApiBase } from './config.js'

async function fetchJson(path) {
  const ctrl = new AbortController()
  const timer = setTimeout(() => ctrl.abort(), FETCH_TIMEOUT_MS)
  const apiBase = resolveApiBase()
  try {
    const res = await fetch(`${apiBase.replace(/\/$/, '')}${path}`, {
      signal: ctrl.signal,
      headers: { Accept: 'application/json' },
    })
    const json = await res.json()
    if (json.code === 2) {
      const err = new Error(json.message || '缓存更新中')
      err.warming = true
      err.retryAfterSec = Number(json.retryAfterSec || 5)
      err.code = 2
      err.staleContext = json.staleContext || null
      throw err
    }
    if (json.code !== 0) throw new Error(json.message || `请求失败 ${res.status}`)
    return json.data
  } finally {
    clearTimeout(timer)
  }
}

export function fetchToday() {
  return fetchJson('/api/sentiment/today')
}

export function fetchHistory(days = 30) {
  return fetchJson(`/api/sentiment/history?days=${days}&tab=day`)
}

export function fetchDay(date) {
  const d = String(date || '').replace(/-/g, '').slice(0, 8)
  if (!d) return Promise.reject(new Error('无效日期'))
  return fetchJson(`/api/sentiment/day?date=${d}`)
}

export function fetchIntradaySeries(date) {
  const d = date ? String(date).replace(/-/g, '').slice(0, 8) : ''
  return fetchJson(d ? `/api/sentiment/intraday-series?date=${d}` : '/api/sentiment/intraday-series')
}

export function fetchAuctionDetail(date) {
  const d = String(date || '').replace(/-/g, '').slice(0, 8)
  const q = d ? `?date=${d}` : ''
  return fetchJson(`/api/auction/detail${q}`)
}
