const { formatDate, getAllRecords, getRecentMatchRates } = require('../../utils/position')
const { getPixelRatio } = require('../../utils/device')

Page({
  data: {
    record: null,
    recentRates: []
  },

  onLoad() {
    const today = formatDate()
    const records = getAllRecords()
    const record = records[today]
    if (!record) {
      wx.showToast({ title: '今日尚未打卡', icon: 'none' })
      setTimeout(() => wx.navigateBack(), 1500)
      return
    }
    this.setData({
      record,
      recentRates: getRecentMatchRates(records, 7)
    })
  },

  onReady() {
    wx.showShareMenu({ withShareTicket: true, menus: ['shareAppMessage', 'shareTimeline'] })
    this.drawCompareBar()
    this.drawHistoryChart()
  },

  onShareAppMessage() {
    const rec = this.data.record
    if (!rec) return { title: '明日当空 - 情绪数据工具' }
    return {
      title: `个人复盘 · 情绪匹配度 ${rec.matchRate}% · ${rec.rating}`,
      path: '/pages/profile/profile',
      imageUrl: rec.imagePath || ''
    }
  },

  onShareTimeline() {
    const rec = this.data.record
    return {
      title: rec ? `明日当空：个人复盘 ${rec.matchRate}% ${rec.rating}` : '明日当空 - 情绪数据工具'
    }
  },

  drawCompareBar() {
    const rec = this.data.record
    if (!rec) return
    const query = wx.createSelectorQuery()
    query.select('#compareBar').fields({ node: true, size: true }).exec(res => {
      if (!res[0]) return
      const canvas = res[0].node
      const ctx = canvas.getContext('2d')
      const dpr = getPixelRatio()
      const w = res[0].width, h = res[0].height
      canvas.width = w * dpr
      canvas.height = h * dpr
      ctx.scale(dpr, dpr)
      ctx.clearRect(0, 0, w, h)
      const barH = 24, y = 40
      ctx.fillStyle = '#F0F0F0'
      ctx.fillRect(0, y, w, barH)
      ctx.fillStyle = '#52C41A'
      ctx.fillRect(0, y, (rec.actualPercent / 100) * w, barH)
      const suggestX = (rec.suggestedPercent / 100) * w
      ctx.strokeStyle = '#FF4D4F'
      ctx.lineWidth = 2
      ctx.beginPath()
      ctx.moveTo(suggestX, y - 8)
      ctx.lineTo(suggestX, y + barH + 8)
      ctx.stroke()
    })
  },

  drawHistoryChart() {
    const query = wx.createSelectorQuery()
    query.select('#historyChart').fields({ node: true, size: true }).exec(res => {
      if (!res[0]) return
      const canvas = res[0].node
      const ctx = canvas.getContext('2d')
      const dpr = getPixelRatio()
      const w = res[0].width, h = res[0].height
      canvas.width = w * dpr
      canvas.height = h * dpr
      ctx.scale(dpr, dpr)
      const data = this.data.recentRates
      const padL = 32, padR = 12, padT = 16, padB = 28
      const chartW = w - padL - padR, chartH = h - padT - padB
      ctx.clearRect(0, 0, w, h)
      const points = data.map((item, i) => ({
        x: padL + (chartW / Math.max(data.length - 1, 1)) * i,
        y: padT + chartH - (item.matchRate / 100) * chartH,
        label: item.date
      }))
      ctx.beginPath()
      ctx.moveTo(points[0].x, points[0].y)
      points.forEach((p, i) => { if (i > 0) ctx.lineTo(p.x, p.y) })
      ctx.strokeStyle = '#52C41A'
      ctx.lineWidth = 2
      ctx.stroke()
    })
  },

  onShare() {
    wx.showShareMenu({ withShareTicket: true })
    wx.showToast({ title: '请点击右上角分享', icon: 'none' })
  },

  goCalendar() {
    wx.navigateTo({ url: '/pages/calendar/calendar' })
  }
})
