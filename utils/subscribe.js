const { SUBSCRIBE_TEMPLATES } = require('./config')
const api = require('./api')

const SUBSCRIBE_LABELS = {
  sentimentDaily: '每日情绪推送',
  emptyAlert: '个人龙空信号提醒'
}

function registerOpenid(type) {
  wx.login({
    success: ({ code }) => {
      if (!code) return
      api.registerSubscribe(code, type === 'emptyAlert' ? 'empty_alert' : 'sentiment_daily')
        .catch(() => {})
    }
  })
}

function requestSubscribe(type = 'sentimentDaily') {
  const tmplId = SUBSCRIBE_TEMPLATES[type] || SUBSCRIBE_TEMPLATES.sentimentDaily
  if (!tmplId) {
    wx.showModal({
      title: '订阅提醒',
      content: '请在 utils/config.js 中配置订阅消息模板 ID。',
      showCancel: false
    })
    return Promise.resolve(false)
  }

  const label = SUBSCRIBE_LABELS[type] || '消息提醒'

  return new Promise(resolve => {
    wx.requestSubscribeMessage({
      tmplIds: [tmplId],
      success(res) {
        const accepted = res[tmplId] === 'accept'
        if (accepted) {
          wx.setStorageSync(`subscribe_${type}`, true)
          registerOpenid(type)
          wx.showToast({ title: `${label}已开启`, icon: 'success' })
        } else if (res[tmplId] === 'reject') {
          wx.showToast({ title: '已取消订阅', icon: 'none' })
        } else {
          wx.showToast({ title: '请在设置中允许订阅消息', icon: 'none' })
        }
        resolve(accepted)
      },
      fail(err) {
        const msg = (err && err.errMsg) || ''
        if (msg.includes('cancel')) {
          resolve(false)
          return
        }
        wx.showToast({ title: '订阅失败，请稍后重试', icon: 'none' })
        resolve(false)
      }
    })
  })
}

module.exports = { requestSubscribe }
