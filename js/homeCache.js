import { beijingDateKey } from './time.js?v=20260609a'

/** 首页 localStorage 缓存：二次打开秒开，后台再刷新 */

const STORAGE_KEY = 'mrdk_home_sentiment_v1'
export const FRESH_TTL_MS = 30 * 60 * 1000
const STALE_MAX_MS = 48 * 60 * 60 * 1000

function todayKey() {
  return beijingDateKey()
}

function readPayload() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const payload = JSON.parse(raw)
    if (!payload?.data) return null
    if (Date.now() - Number(payload.ts || 0) > STALE_MAX_MS) return null
    if (payload.day && payload.day !== todayKey()) return null
    return payload
  } catch {
    return null
  }
}

export function getHomeCache() {
  return readPayload()?.data || null
}

export function getHomeCacheMeta() {
  return readPayload()
}

export function shouldRefreshHomeCache() {
  const meta = readPayload()
  if (!meta?.data) return true
  return Date.now() - Number(meta.ts || 0) > FRESH_TTL_MS
}

export function saveHomeCache(data) {
  if (!data) return
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({
      ts: Date.now(),
      day: todayKey(),
      data,
    }))
  } catch {
    /* quota */
  }
}

export function isSameHomeSnapshot(a, b) {
  if (!a || !b) return false
  const refA = String(a.refDate || a.adviceDate || '').replace(/\D/g, '').slice(0, 8)
  const refB = String(b.refDate || b.adviceDate || '').replace(/\D/g, '').slice(0, 8)
  return refA === refB
    && Number(a.displayScore ?? a.score) === Number(b.displayScore ?? b.score)
    && String(a.generatedAtLabel || a.generatedAt || '') === String(b.generatedAtLabel || b.generatedAt || '')
}
