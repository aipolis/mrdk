const { fetchHistory, getHistoryCache } = require('../../utils/store')
const { getDisplayLevel } = require('../../utils/theme')
const { getChartColors } = require('../../utils/uiTheme')
const uiThemeBehavior = require('../../behaviors/uiTheme')

const PERIODS = [
  { days: 5, label: '近5日' },
  { days: 10, label: '近10日' },
  { days: 20, label: '近20日' },
]

function barColorForScore(score) {
  const s = Number(score) || 0
  if (s > 70) return '#e63838'
  if (s >= 30) return '#f5a60a'
  return '#91d1ed'
}

Page({
  behaviors: [uiThemeBehavior],

  data: {
    loading: true,
    list: [],
    warming: false,
    trendDays: 10,
    periods: PERIODS,
  },

  onLoad() {
    this.loadData()
  },

  onReady() {
    wx.nextTick(() => this.drawTrend())
  },

  onPullDownRefresh() {
    this.loadData(true).finally(() => wx.stopPullDownRefresh())
  },

  applyList(rawList) {
    const list = (rawList || []).map(item => ({
      ...item,
      dateShort: this.formatDateShort(item.date),
      level: item.level || this.scoreToLevel(item.score),
      levelClass: item.levelClass || this.getLevelClass(item.score),
      indexChgText: item.indexChgText != null
        ? item.indexChgText
        : `${(item.indexChg || 0) >= 0 ? '+' : ''}${Number(item.indexChg || 0).toFixed(2)}%`,
      indexUp: item.indexUp != null ? item.indexUp : (item.indexChg || 0) >= 0
    }))
    this.setData({ list })
    return list
  },

  loadData(forceRefresh = false) {
    const cached = !forceRefresh && getHistoryCache()
    if (cached && cached.length) {
      this.applyList(cached)
      this.setData({ loading: false }, () => this.drawTrend())
    } else {
      this.setData({ loading: true, warming: false })
    }

    return fetchHistory(30, { force: forceRefresh })
      .then(data => {
        const list = data.list || []
        if (list.length) {
          this.applyList(list)
          this.setData({ loading: false, warming: false }, () => this.drawTrend())
        } else if (data.warming) {
          this.setData({ loading: false, warming: true }, () => this.drawTrend())
        } else {
          this.setData({ loading: false, warming: false }, () => this.drawTrend())
        }
      })
      .catch(() => {
        if (!this.data.list.length) {
          this.applyList(require('../../utils/data').historyData.slice().reverse())
        }
        this.setData({ loading: false, warming: false }, () => this.drawTrend())
      })
  },

  onPeriodTap(e) {
    const days = Number(e.currentTarget.dataset.days) || 10
    if (days === this.data.trendDays) return
    this.setData({ trendDays: days }, () => this.drawTrend())
  },

  drawTrend() {
    const colors = getChartColors(this.data.uiTheme)
    const query = wx.createSelectorQuery().in(this)
    query.select('#trendCanvas').fields({ node: true, size: true }).exec(res => {
      if (!res[0] || !res[0].node || !res[0].width) return
      const canvas = res[0].node
      const ctx = canvas.getContext('2d')
      const dpr = wx.getSystemInfoSync().pixelRatio || 2
      const w = res[0].width
      const h = res[0].height
      canvas.width = w * dpr
      canvas.height = h * dpr
      ctx.scale(dpr, dpr)
      ctx.clearRect(0, 0, w, h)

      const days = this.data.trendDays
      const list = this.data.list.slice(0, days).reverse()
      if (!list.length) return

      const font = '-apple-system, BlinkMacSystemFont, PingFang SC, sans-serif'
      const padL = 20
      const padR = 20
      const padT = 28
      const padB = 30
      const n = list.length
      const chartW = w - padL - padR
      const chartH = h - padT - padB
      const barGap = 4
      const barW = Math.max(8, Math.round((chartW - barGap * (n - 1)) / n * 2) / 2)

      // grid lines
      for (let i = 0; i <= 4; i++) {
        const y = Math.round(padT + (chartH / 4) * i * 2) / 2
        ctx.strokeStyle = colors.grid
        ctx.lineWidth = 1
        ctx.beginPath()
        ctx.moveTo(padL, y)
        ctx.lineTo(w - padR, y)
        ctx.stroke()
      }

      // bars
      list.forEach((item, i) => {
        const barX = Math.round((padL + i * (barW + barGap)) * 2) / 2
        const barH = Math.max(4, Math.round((Math.max(0, Math.min(100, item.score)) / 100) * chartH * 2) / 2)
        const barY = Math.round((padT + chartH - barH) * 2) / 2
        const r = Math.min(4, barW / 2)

        ctx.fillStyle = barColorForScore(item.score)
        ctx.beginPath()
        ctx.moveTo(barX, padT + chartH)
        ctx.lineTo(barX, barY + r)
        ctx.quadraticCurveTo(barX, barY, barX + r, barY)
        ctx.lineTo(barX + barW - r, barY)
        ctx.quadraticCurveTo(barX + barW, barY, barX + barW, barY + r)
        ctx.lineTo(barX + barW, padT + chartH)
        ctx.closePath()
        ctx.fill()

        // score label
        ctx.fillStyle = colors.textPrimary || '#0f172a'
        ctx.font = `600 10px ${font}`
        ctx.textAlign = 'center'
        ctx.textBaseline = 'bottom'
        ctx.fillText(String(item.score), barX + barW / 2, barY - 3)

        // date label
        const dateLabel = this.formatDateShort(item.date)
        ctx.fillStyle = colors.textMuted
        ctx.font = `9px ${font}`
        ctx.textBaseline = 'top'
        ctx.fillText(dateLabel, barX + barW / 2, padT + chartH + 6)
      })
    })
  },

  formatDateShort(dateStr) {
    if (!dateStr) return ''
    const parts = String(dateStr).split('-')
    if (parts.length >= 3) return `${parts[1]}-${parts[2]}`
    return dateStr
  },

  getLevelClass(score) {
    return getDisplayLevel(score).class
  },

  scoreToLevel(score) {
    return getDisplayLevel(score).label
  }
})
