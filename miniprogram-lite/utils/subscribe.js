const { SUBSCRIBE_TEMPLATES } = require('./config')
const api = require('./api')

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
          wx.setStorageSync('subscribe_sentimentDaily', true)
          registerOpenid()
          wx.showToast({ title: '已开启提醒，避免淋雨', icon: 'success' })
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

module.exports = { requestDailySubscribe }
