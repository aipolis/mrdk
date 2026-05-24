/** 历史页列表本地缓存 */

const STORAGE_KEY = 'history_list_v1'
const STALE_MAX_MS = 48 * 60 * 60 * 1000

function saveHistoryCache(list) {
  if (!list || !list.length) return
  try {
    wx.setStorageSync(STORAGE_KEY, { ts: Date.now(), list })
  } catch (e) {
    /* ignore */
  }
}

function getHistoryCache() {
  try {
    const stored = wx.getStorageSync(STORAGE_KEY)
    if (!stored || !stored.list || !stored.list.length) return null
    if (Date.now() - stored.ts > STALE_MAX_MS) return null
    return stored.list
  } catch (e) {
    return null
  }
}

module.exports = {
  saveHistoryCache,
  getHistoryCache,
}
