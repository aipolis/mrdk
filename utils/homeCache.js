const { getLocalCalendarKey } = require('./dateDisplay')

/** 首页情绪数据本地缓存：启动预取 + 打开秒开 */

const STORAGE_KEY = 'home_sentiment_v1'
const MEM_KEY = 'homeSentimentCache'

/** 超过此时间仍展示缓存，但会在后台静默刷新 */
const FRESH_TTL_MS = 30 * 60 * 1000

/** 超过此时间视为过期，不再使用 */
const STALE_MAX_MS = 48 * 60 * 60 * 1000

function readPayload() {
  try {
    const app = getApp()
    if (app && app.globalData && app.globalData[MEM_KEY]) {
      return app.globalData[MEM_KEY]
    }
    const stored = wx.getStorageSync(STORAGE_KEY)
    if (stored && stored.data) {
      if (app && app.globalData) app.globalData[MEM_KEY] = stored
      return stored
    }
  } catch (e) {
    /* ignore */
  }
  return null
}

function saveHomeCache(data) {
  if (!data) return
  const payload = { ts: Date.now(), calendarDay: getLocalCalendarKey(), data }
  try {
    wx.setStorageSync(STORAGE_KEY, payload)
  } catch (e) {
    /* ignore quota */
  }
  try {
    const app = getApp()
    if (app && app.globalData) app.globalData[MEM_KEY] = payload
  } catch (e) {
    /* ignore */
  }
}

function getHomeCache() {
  const payload = readPayload()
  if (!payload || !payload.data) return null
  if (Date.now() - payload.ts > STALE_MAX_MS) return null
  if (payload.calendarDay && payload.calendarDay !== getLocalCalendarKey()) return null
  return payload.data
}

function getHomeCacheMeta() {
  const payload = readPayload()
  if (!payload || !payload.data) return null
  if (Date.now() - payload.ts > STALE_MAX_MS) return null
  if (payload.calendarDay && payload.calendarDay !== getLocalCalendarKey()) return null
  return payload
}

function shouldRefreshHomeCache() {
  const payload = readPayload()
  if (!payload) return true
  return Date.now() - payload.ts > FRESH_TTL_MS
}

function isSameHomeSnapshot(a, b) {
  if (!a || !b) return false
  const scoreA = a.displayScore != null ? a.displayScore : a.score
  const scoreB = b.displayScore != null ? b.displayScore : b.score
  return (
    scoreA === scoreB
    && (a.adviceDate || a.date) === (b.adviceDate || b.date)
    && a.generatedAt === b.generatedAt
    && (a.refDate || '') === (b.refDate || '')
  )
}

function warmHomeCacheFromStorage() {
  readPayload()
}

module.exports = {
  saveHomeCache,
  getHomeCache,
  getHomeCacheMeta,
  shouldRefreshHomeCache,
  isSameHomeSnapshot,
  warmHomeCacheFromStorage,
  FRESH_TTL_MS,
}
