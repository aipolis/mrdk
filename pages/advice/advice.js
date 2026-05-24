const api = require('../../utils/api')
const { getPixelRatio } = require('../../utils/device')
const { getDisplayLevel } = require('../../utils/theme')

Page({
  data: {
    percent: 0,
    score: 0,
    levelLabel: '',
    label: '',
    rule: '',
    reminders: [],
    strategies: [],
    markers: ['冰点', '谨慎', '活跃', '亢奋']
  },

  onLoad() {
    api.getAdvice().then(data => {
      const level = getDisplayLevel(data.score || 0)
      this.setData({
        percent: data.percent,
        score: data.score || 0,
        levelLabel: level.label,
        label: data.label,
        rule: data.rule,
        reminders: data.reminders,
        strategies: data.strategies
      }, () => this.drawPositionGauge())
    }).catch(() => {
      this.drawPositionGauge()
    })
  },
  onReady() {
    this.drawPositionGauge()
  },

  drawPositionGauge() {
    const query = wx.createSelectorQuery()
    query.select('#posGauge').fields({ node: true, size: true }).exec(res => {
      if (!res[0] || !res[0].node) return
      const canvas = res[0].node
      const ctx = canvas.getContext('2d')
      const dpr = getPixelRatio()
      const w = res[0].width, h = res[0].height
      canvas.width = w * dpr
      canvas.height = h * dpr
      ctx.scale(dpr, dpr)
      const cx = w / 2, cy = h * 0.85, r = Math.min(w, h) * 0.42
      const percent = this.data.percent
      ctx.clearRect(0, 0, w, h)
      ctx.beginPath()
      ctx.arc(cx, cy, r, Math.PI, 2 * Math.PI)
      ctx.lineWidth = 16
      ctx.strokeStyle = '#F0F0F0'
      ctx.stroke()
      if (percent > 0) {
        ctx.beginPath()
        ctx.arc(cx, cy, r, Math.PI, Math.PI + (percent / 100) * Math.PI)
        ctx.lineWidth = 16
        ctx.strokeStyle = '#FF4D4F'
        ctx.lineCap = 'round'
        ctx.stroke()
      }
      ctx.fillStyle = '#333'
      ctx.font = 'bold 28px sans-serif'
      ctx.textAlign = 'center'
      ctx.fillText(String(this.data.score), cx, cy - 20)
      ctx.font = '14px sans-serif'
      ctx.fillStyle = '#666'
      ctx.fillText(this.data.levelLabel, cx, cy + 4)
    })
  }
})
