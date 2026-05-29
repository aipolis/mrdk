import { FETCH_TIMEOUT_MS } from './config.js'

// 动态解析API_BASE，支持运行时切换（开发调试用）
function resolveApiBase() {
  if (typeof window !== 'undefined' && window.__API_BASE__) {
    return window.__API_BASE__
  }
  if (typeof localStorage !== 'undefined') {
    const stored = localStorage.getItem('mrdk_api_base')
    if (stored && stored.trim()) return stored.trim()
  }
  if (typeof process !== 'undefined' && process.env && process.env.VITE_API_BASE) {
    return process.env.VITE_API_BASE
  }
  return 'https://mingri-api-260693-8-1435576840.sh.run.tcloudbase.com'
}

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
