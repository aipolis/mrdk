const { fetchHome, applyHomeData, getHomeCache } = require('../../utils/store')
const { withPreviewScore } = require('../../utils/preview')
const { homeData } = require('../../utils/data')
const { getDisplayLevel } = require('../../utils/theme')
const { normalizeIndicatorSections } = require('../../utils/indicators')
const { drawSteeringGauge } = require('../../utils/gaugeDraw')
const { setupCanvas2d } = require('../../utils/device')
const uiThemeBehavior = require('../../behaviors/uiTheme')

Page({
  behaviors: [uiThemeBehavior],

  data: {
    score: 0,
    levelLabel: '',
    levelClass: '',
    positionDesc: '',
    indicatorSections: []
  },

  onLoad() {
    const cached = getHomeCache()
    if (cached) this.apply(cached)
    fetchHome()
      .then(data => this.apply(data))
      .catch(() => {
        if (!cached) this.apply(applyHomeData(homeData))
      })
  },

  onReady() {
    this.drawShareGauge()
  },

  onUiThemeChange() {
    this.drawShareGauge()
  },

  apply(data) {
    data = withPreviewScore(data)
    const level = getDisplayLevel(data.score)
    this.setData({
      score: data.score,
      levelLabel: data.displayLevel || data.levelLabel || level.label,
      levelClass: data.levelClass || level.class,
      positionDesc: data.positionDesc,
      indicatorSections: normalizeIndicatorSections(data)
    }, () => this.drawShareGauge())
  },

  drawShareGauge() {
    const query = wx.createSelectorQuery()
    query.select('#shareGauge').fields({ node: true, size: true }).exec(res => {
      if (!res[0] || !res[0].node) return
      const canvas = res[0].node
      const ctx = canvas.getContext('2d')
      const { width, height } = setupCanvas2d(canvas, ctx, res[0].width, res[0].height)
      drawSteeringGauge(ctx, width, height, this.data.score, this.data.uiTheme)
    })
  },

  onShareAppMessage() {
    return {
      title: `明日当空 · 情绪${this.data.score}分 ${this.data.levelLabel}`,
      path: '/pages/index/index'
    }
  }
})
