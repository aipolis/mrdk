const api = require('./api')
const { mapToday, mapHistoryList, formatUpdateBadge, formatHeaderDate } = require('./verdict')
const { mapTrendBars } = require('./trend')

const CACHE_KEY = 'lite_today_v1'
const TREND_CACHE_KEY = 'lite_trend_v1'
const HISTORY_CACHE_KEY = 'lite_history_v1'

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

function loadCachedTrend() {
  try {
    return wx.getStorageSync(TREND_CACHE_KEY) || null
  } catch (e) { /* ignore */ }
  return null
}

function saveCachedTrend(bars) {
  try {
    wx.setStorageSync(TREND_CACHE_KEY, bars)
  } catch (e) { /* ignore */ }
}

function loadCachedHistory() {
  try {
    return wx.getStorageSync(HISTORY_CACHE_KEY) || null
  } catch (e) { /* ignore */ }
  return null
}

function saveCachedHistory(list) {
  try {
    wx.setStorageSync(HISTORY_CACHE_KEY, list)
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
  return api.getHistory(days).then(data => {
    const list = mapHistoryList(data.list || [])
    saveCachedHistory(list)
    return list
  })
}

/** 只拉取原始历史列表（用于今日页并行加载走势，超时短因为有缓存兜底） */
function fetchHistoryRaw(days) {
  return api.getHistory(days + 6, { timeout: 15000 }).then(data => data.list || [])
}

function fetchTrend(days = 10, todayRaw) {
  return api.getHistory(days + 6, { timeout: 15000 }).then(data => {
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
  fetchHistoryRaw,
  fetchTrend,
  loadCachedToday,
  loadCachedTrend,
  saveCachedTrend,
  loadCachedHistory,
  saveCachedHistory,
}
