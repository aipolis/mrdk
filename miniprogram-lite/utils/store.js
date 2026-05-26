const api = require('./api')
const { mapToday, mapHistoryList, formatUpdateBadge, formatHeaderDate } = require('./verdict')
const { mapTrendBars } = require('./trend')

const CACHE_KEY = 'lite_today_v1'

function loadCachedToday() {
  try {
    const cached = wx.getStorageSync(CACHE_KEY)
    if (!cached || !cached.verdict) return null
    return {
      ...cached,
      headerDate: formatHeaderDate(),
      updateBadge: cached.raw ? formatUpdateBadge(cached.raw) : (cached.updateBadge || ''),
    }
  } catch (e) { /* ignore */ }
  return null
}

function saveCachedToday(mapped) {
  try {
    wx.setStorageSync(CACHE_KEY, { ...mapped, cachedAt: Date.now() })
  } catch (e) { /* ignore */ }
}

function fetchToday(options = {}) {
  return api.getTodaySentimentWithRetry({ ...options, maxAttempts: options.maxAttempts || 3 }).then(raw => {
    const mapped = mapToday(raw)
    saveCachedToday(mapped)
    return mapped
  })
}

function fetchHistory(days = 30) {
  return api.getHistory(days).then(data => mapHistoryList(data.list || []))
}

function fetchTrend(days = 10, todayRaw) {
  return api.getHistory(days).then(data => {
    const todayItem = todayRaw
      ? {
          date: todayRaw.refDate || todayRaw.date,
          score: todayRaw.displayScore != null ? todayRaw.displayScore : todayRaw.score,
          levelClass: todayRaw.levelClass,
          levelColor: todayRaw.levelColor,
        }
      : null
    return mapTrendBars(data.list || [], todayItem, days)
  })
}

module.exports = {
  fetchToday,
  fetchHistory,
  fetchTrend,
  loadCachedToday,
}
