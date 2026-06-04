const { SUBSCRIBE_TEMPLATES } = require('./config')
const api = require('./api')

const STORAGE_KEY = 'subscribe_sentimentDaily'

function todayStr() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

/** 今天是否已授权（一次性订阅：每天重置） */
function isSubscribedToday() {
  try {
    return wx.getStorageSync(STORAGE_KEY) === todayStr()
  } catch (e) { return false }
}

function setSubscribedToday() {
  try {
    wx.setStorageSync(STORAGE_KEY, todayStr())
  } catch (e) {}
}

function registerOpenid() {
  wx.login({
    success: ({ code }) => {
      if (!code) return
      api.registerSubscribe(code, 'sentiment_daily').catch(() => {})
    },
  })
}

function requestDailySubscribe() {
  const tmplId = SUBSCRIBE_TEMPLATES.sentimentDaily
  if (!tmplId) {
    wx.showModal({
      title: '提醒',
      content: '请在 utils/config.js 配置订阅模板 ID',
      showCancel: false,
    })
    return Promise.resolve(false)
  }
  return new Promise(resolve => {
    wx.requestSubscribeMessage({
      tmplIds: [tmplId],
      success(res) {
        const ok = res[tmplId] === 'accept'
        if (ok) {
          setSubscribedToday()
          registerOpenid()
          wx.showToast({ title: '已预约今日提醒', icon: 'success' })
        } else if (res[tmplId] === 'reject') {
          wx.showToast({ title: '已取消', icon: 'none' })
        }
        resolve(ok)
      },
      fail() {
        wx.showToast({ title: '订阅失败', icon: 'none' })
        resolve(false)
      },
    })
  })
}

module.exports = { requestDailySubscribe, isSubscribedToday }
