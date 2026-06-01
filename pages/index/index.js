const { orderIndicatorSections, normalizeIndicatorSections } = require('../../utils/indicators')
const { fetchHomeFromNetwork, applyHomeData, getHomeCache, isSameHomeSnapshot, fetchHistory } = require('../../utils/store')
const { withPreviewScore } = require('../../utils/preview')
const { homeData } = require('../../utils/data')
const { getDisplayLevel, dailyQuote, normalizeQuote, formatQuoteText, HOME_QUOTE } = require('../../utils/theme')
const { setupCanvas2d, getCustomNavLayout } = require('../../utils/device')
const { createGaugeController, SKIP_ANIM_MS, CACHE_IDLE_MS } = require('../../utils/gaugeAnim')
const { getChartColors } = require('../../utils/uiTheme')
const uiThemeBehavior = require('../../behaviors/uiTheme')
const { createSharePoster, savePosterToAlbum, forwardPosterImage } = require('../../utils/shareImage')
const { formatHeaderDate, formatGaugeUpdatedAt, buildStatusText } = require('../../utils/dateDisplay')
const { resolveLongkongState, resolveLongkongTone, buildLongkongHeroText } = require('../../utils/longkongState')

const LOADING_DESC = '正在汇总昨日收盘数据…'

const TREND_PERIODS = [
  { days: 5, label: '近5日' },
  { days: 10, label: '近10日' },
  { days: 20, label: '近20日' },
]

function barColorForScore(score) {
  const s = Number(score) || 0
  if (s >= 90) return '#cf1322'
  if (s >= 80) return '#cf1322'
  if (s >= 60) return '#ff4d4f'
  if (s >= 50) return '#faad14'
  if (s >= 40) return '#52c41a'
  if (s >= 30) return '#38bdf8'
  return '#1890ff'
}

Page({
  behaviors: [uiThemeBehavior],

  data: {
    loading: true,
    scoreCalculating: true,
    scoreRevealing: false,
    displayScore: '',
    displayAdviceDate: '',
    statusText: '数据加载中…',
    refDate: '',
    generatedAt: '更新中',
    sectorConcentration: { topSectors: [] },
    dailyQuoteText: '',
    dailyQuoteAuthor: '',
    score: 0,
    baselineScore: null,
    liveScore: null,
    scoreMode: 'baseline',
    levelLabel: '',
    levelClass: '',
    positionDesc: LOADING_DESC,
    isEmptyPosition: false,
    emptyReasons: [],
    longkongStateKey: '',
    longkongStateLabel: '',
    longkongHeroLevel: '',
    longkongHeroDesc: '',
    longkongLevelClass: 'neutral',
    longkongStateSteps: [],
    quoteFontReady: false,
    trend: [],
    trendDays: 10,
    trendPeriods: TREND_PERIODS,
    historyList: [],
    navCapSafeHeight: 88,
    navSpacerHeight: 140,
    sharePosterVisible: false,
    sharePosterPath: '',
    sharePosterSaving: false,
    sharePosterForwarding: false,
  },

  onLoad() {
    this._gaugeCtrl = createGaugeController(this)
    this._pendingGaugeMeta = null
    this.setData(getCustomNavLayout())
    this.applyQuoteData(HOME_QUOTE)
    const app = getApp()
    this.setData({ quoteFontReady: !!(app.globalData && app.globalData.quoteFontReady) })
    this.loadQuoteFontFace()
    this.loadData().catch(() => {})
  },

  loadQuoteFontFace() {
    const { loadQuoteFont } = require('../../utils/quoteFont')
    return loadQuoteFont().then(ok => {
      this.setData({ quoteFontReady: !!ok })
      if (getApp().globalData) getApp().globalData.quoteFontReady = !!ok
    })
  },

  onShow() {
    this.syncUiTheme(false)
    this.setData({ displayAdviceDate: formatHeaderDate() })
    if (!this.data.quoteFontReady) this.loadQuoteFontFace()
    this.syncIndicatorSectionOrder()
    this._startPolling()
  },

  onHide() {
    this._stopPolling()
  },

  syncIndicatorSectionOrder() {
    const sections = this.data.indicatorSections
    if (!sections || !sections.length) return
    const ordered = orderIndicatorSections(sections)
    const prevIds = sections.map(s => s.id).join(',')
    const nextIds = ordered.map(s => s.id).join(',')
    if (prevIds !== nextIds) {
      this.setData({ indicatorSections: ordered })
    }
  },

  onUiThemeChange() {
    if (this._gaugeCtrl && this._gaugeCtrl.ctx && !this.data.scoreCalculating && this.data.score) {
      this._gaugeCtrl.drawFinal(this.data.score)
    }
    if ((this.data.historyList && this.data.historyList.length) || (this.data.trend && this.data.trend.length)) {
      this.drawTrend()
    }
  },

  onUnload() {
    this._stopPolling()
    if (this._gaugeIdleTimer) clearTimeout(this._gaugeIdleTimer)
    if (this._gaugeCtrl) this._gaugeCtrl.stop()
  },

  _getPollIntervalMs() {
    const now = new Date()
    const hm = now.getHours() * 60 + now.getMinutes()
    if (hm >= 9 * 60 + 15 && hm < 9 * 60 + 26) return 20000
    if (hm >= 9 * 60 + 25 && hm <= 15 * 60 + 5) return 120000
    return 0
  },

  _isTradingHours() {
    return this._getPollIntervalMs() > 0
  },

  _startPolling() {
    this._stopPolling()
    const interval = this._getPollIntervalMs()
    if (!interval) return
    this._pollTimer = setTimeout(() => {
      this._silentRefresh()
      this._pollInterval = setInterval(() => {
        const ms = this._getPollIntervalMs()
        if (!ms) {
          this._stopPolling()
          return
        }
        if (ms !== interval && this._pollInterval) {
          this._stopPolling()
          this._startPolling()
          return
        }
        this._silentRefresh()
      }, interval)
    }, 3000)
  },

  _stopPolling() {
    if (this._pollTimer) {
      clearTimeout(this._pollTimer)
      this._pollTimer = null
    }
    if (this._pollInterval) {
      clearInterval(this._pollInterval)
      this._pollInterval = null
    }
  },

  _silentRefresh() {
    if (this._refreshing) return
    this._refreshing = true
    const prevCache = getHomeCache()
    Promise.all([
      fetchHomeFromNetwork({ reuseInflight: false }),
      fetchHistory(20).catch(() => ({ list: [] })),
    ])
      .then(([data, histData]) => {
        const histList = (histData && histData.list) || data.historyList || []
        if (!prevCache || !isSameHomeSnapshot(prevCache, data)) {
          this.applyPageData({ ...data, historyList: histList }, { silent: true })
        } else {
          this.setData({
            historyList: histList,
            indicatorSections: data.indicatorSections || this.data.indicatorSections,
          }, () => this.drawTrend())
        }
      })
      .catch(() => {})
      .finally(() => {
        this._refreshing = false
      })
  },

  onPullDownRefresh() {
    this.loadData(true).catch(() => {}).finally(() => wx.stopPullDownRefresh())
  },

  onReady() {
    wx.nextTick(() => this.bootstrapGauge())
  },

  applyQuoteData(raw) {
    const item = normalizeQuote(raw || HOME_QUOTE)
    this.setData({
      dailyQuoteText: formatQuoteText(item.text),
      dailyQuoteAuthor: item.author
    })
  },

  resolveHeaderDate() {
    return formatHeaderDate()
  },

  resolveGaugeUpdatedAt(data) {
    return formatGaugeUpdatedAt(data || {
      refDate: this.data.refDate,
      generatedAtLabel: this.data.generatedAt
    })
  },

  buildLongkongHeroFields(data, longkongState, overrides = {}) {
    const riskDesc = data.emptyWarning ? '分数中性，但接力晋级偏弱' : ''
    const positionDesc = overrides.positionDesc != null
      ? overrides.positionDesc
      : (riskDesc || data.positionDesc || '')
    const merged = {
      ...data,
      positionDesc,
      levelLabel: overrides.levelLabel != null
        ? overrides.levelLabel
        : (data.displayLevel || data.levelLabel || ''),
      displayScore: overrides.displayScore != null
        ? overrides.displayScore
        : (data.displayScore != null ? data.displayScore : data.score),
    }
    const hero = buildLongkongHeroText(merged, longkongState)
    return {
      longkongStateLabel: longkongState.label,
      longkongHeroLevel: hero.levelLabel,
      longkongHeroDesc: hero.desc,
    }
  },

  applyPageData(data, options = {}) {
    const { fromCache = false, silent = false } = options
    data = withPreviewScore(data)
    data = {
      ...data,
      indicatorSections: normalizeIndicatorSections(data),
    }
    const gaugeScore = data.displayScore != null ? data.displayScore : data.score
    const level = getDisplayLevel(gaugeScore)
    const finalScore = gaugeScore
    const elapsed = Date.now() - (this._loadStartAt || 0)
    const skipAnim = silent || (!fromCache && elapsed < SKIP_ANIM_MS)

    this._pendingGaugeMeta = {
      levelLabel: data.displayLevel || data.levelLabel || level.label,
      levelClass: data.levelClass || level.class,
      positionDesc: data.positionDesc,
      baselineScore: data.baselineScore != null ? data.baselineScore : data.score,
      scoreMode: data.scoreMode || 'baseline',
    }

    getApp().setTodaySentiment(finalScore, {
      percent: data.positionPercent,
      label: data.positionLabel
    })

    const quote = normalizeQuote(HOME_QUOTE)
    const refDate = data.refDate || data.adviceDate || data.date || ''
    const longkongState = resolveLongkongState(data)
    const longkongTone = resolveLongkongTone(data)
    const positionDesc = skipAnim
      ? (data.emptyWarning ? '分数中性，但接力晋级偏弱' : (this._pendingGaugeMeta.positionDesc || data.positionDesc))
      : LOADING_DESC
    const levelLabel = skipAnim
      ? (this._pendingGaugeMeta.levelLabel || level.label)
      : '计算中'
    const heroFields = this.buildLongkongHeroFields(data, longkongState, {
      positionDesc,
      levelLabel,
      displayScore: finalScore,
    })

    this.setData({
      loading: false,
      displayAdviceDate: this.resolveHeaderDate(),
      refDate,
      generatedAt: this.resolveGaugeUpdatedAt(data),
      dailyQuoteText: formatQuoteText(quote.text),
      dailyQuoteAuthor: quote.author,
      score: finalScore,
      baselineScore: data.baselineScore != null ? data.baselineScore : data.score,
      liveScore: data.liveScore,
      scoreMode: data.scoreMode || 'baseline',
      isEmptyPosition: !!data.emptyWarning,
      emptyReasons: data.emptyReasons || [],
      longkongStateKey: longkongState.state,
      longkongLevelClass: longkongTone.class,
      longkongStateSteps: longkongState.steps || [],
      ...heroFields,
      statusText: buildStatusText(data),
      indicatorSections: data.indicatorSections || [],
      sectorConcentration: data.sectorConcentration || { topSectors: [] },
      trend: data.trend || [],
      historyList: data.historyList || [],
      trendDays: this.data.trendDays || 10,
      positionDesc,
      levelLabel: skipAnim ? levelLabel : '',
      levelClass: skipAnim ? (this._pendingGaugeMeta.levelClass || level.class) : '',
    }, () => {
      wx.nextTick(() => {
        this.finishGaugeAnimation(finalScore, skipAnim, level, {
          minIdleMs: fromCache && !skipAnim ? CACHE_IDLE_MS : 0,
        })
        this.drawTrend()
      })
    })
  },

  bootstrapGauge(retry = 0) {
    this.bindGaugeCanvas(() => {
      if (this.data.scoreCalculating) {
        this._gaugeCtrl.startIdle()
      } else if (this.data.score) {
        this._gaugeCtrl.drawFinal(this.data.score)
      }
    }, retry)
  },

  bindGaugeCanvas(onReady, retry = 0) {
    const query = wx.createSelectorQuery().in(this)
    query.select('#gaugeCanvas').fields({ node: true, size: true }).exec(res => {
      if (!res[0] || !res[0].node || !res[0].width) {
        if (retry < 5) {
          setTimeout(() => this.bindGaugeCanvas(onReady, retry + 1), 80)
        }
        return
      }
      const canvas = res[0].node
      const ctx = canvas.getContext('2d')
      const { width, height } = setupCanvas2d(canvas, ctx, res[0].width, res[0].height)
      this._gaugeCtrl.bindCanvas(canvas, ctx, width, height)
      if (onReady) onReady()
    })
  },

  finishGaugeAnimation(finalScore, skipAnim, level, opts = {}) {
    const minIdleMs = opts.minIdleMs || 0
    const applyMeta = () => {
      const meta = this._pendingGaugeMeta || {}
      const riskDesc = this.data.isEmptyPosition ? '分数中性，但接力晋级偏弱' : ''
      const positionDesc = riskDesc || meta.positionDesc || this.data.positionDesc
      const levelLabel = meta.levelLabel || level.label
      const levelClass = meta.levelClass || level.class
      const lk = resolveLongkongState({
        ...this.data,
        emptyWarning: this.data.isEmptyPosition,
        displayScore: finalScore,
        positionDesc,
      })
      const heroFields = this.buildLongkongHeroFields(
        { ...this.data, emptyWarning: this.data.isEmptyPosition, positionDesc },
        lk,
        { positionDesc, levelLabel, displayScore: finalScore }
      )
      this.setData({
        scoreCalculating: false,
        scoreRevealing: false,
        displayScore: String(finalScore),
        baselineScore: meta.baselineScore,
        scoreMode: meta.scoreMode || 'baseline',
        levelLabel,
        levelClass,
        positionDesc,
        longkongStateKey: lk.state,
        longkongLevelClass: resolveLongkongTone({ displayScore: finalScore }).class,
        longkongStateSteps: lk.steps || [],
        ...heroFields,
      })
    }

    const runSettle = () => {
      this.setData({ scoreCalculating: true, scoreRevealing: false, displayScore: '' })
      this._gaugeCtrl.settleTo(finalScore, applyMeta)
    }

    const run = () => {
      if (skipAnim) {
        this._gaugeCtrl.drawFinal(finalScore)
        applyMeta()
        return
      }
      if (minIdleMs > 0) {
        if (this._gaugeCtrl.mode !== 'idle') {
          this._gaugeCtrl.startIdle()
        }
        const elapsed = Date.now() - (this._cacheAnimStart || Date.now())
        const remain = Math.max(0, minIdleMs - elapsed)
        if (this._gaugeIdleTimer) clearTimeout(this._gaugeIdleTimer)
        this._gaugeIdleTimer = setTimeout(runSettle, remain)
        return
      }
      runSettle()
    }

    if (this._gaugeCtrl.ctx) {
      run()
    } else {
      this.bindGaugeCanvas(run)
    }
  },

  loadData(forceRefresh = false) {
    this._loadStartAt = Date.now()
    const cached = !forceRefresh && getHomeCache()

    if (cached) {
      this._cacheAnimStart = Date.now()
      if (this._gaugeCtrl) this._gaugeCtrl.stop()
      wx.nextTick(() => {
        if (this._gaugeCtrl && this._gaugeCtrl.ctx) {
          this._gaugeCtrl.startIdle()
        } else {
          this.bootstrapGauge()
        }
      })
      this.applyPageData(cached, { fromCache: true })
    } else {
      if (this._gaugeCtrl) this._gaugeCtrl.stop()
      this.setData({
        loading: true,
        scoreCalculating: true,
        scoreRevealing: false,
        displayScore: '',
        levelLabel: '',
        levelClass: '',
        positionDesc: LOADING_DESC,
        isEmptyPosition: false,
        emptyReasons: [],
      }, () => {
        wx.nextTick(() => {
          if (this._gaugeCtrl && this._gaugeCtrl.ctx) {
            this._gaugeCtrl.startIdle()
          } else {
            this.bootstrapGauge()
          }
        })
      })
    }

    return Promise.all([
      fetchHomeFromNetwork({ reuseInflight: !forceRefresh, force: forceRefresh }),
      fetchHistory(20, { force: forceRefresh }).catch(() => ({ list: [] })),
    ])
      .then(([data, histData]) => {
        const histList = (histData && histData.list) || data.historyList || []
        if (!cached || !isSameHomeSnapshot(cached, data)) {
          this.applyPageData({ ...data, historyList: histList }, { silent: !!cached })
        } else {
          this.setData({
            historyList: histList,
            indicatorSections: data.indicatorSections || this.data.indicatorSections,
          }, () => this.drawTrend())
        }
      })
      .catch(err => {
        if (!cached) {
          this.applyPageData(applyHomeData(homeData), { fromCache: true })
        }
        if (forceRefresh) {
          const msg = String((err && (err.errMsg || err.message)) || err || '')
          if (/timeout|timed out/i.test(msg)) {
            wx.showToast({ title: '网络较慢，已显示缓存', icon: 'none' })
          }
        }
      })
  },

  drawCanvas(selector, drawFn, retry = 0) {
    const query = wx.createSelectorQuery().in(this)
    query.select(selector).fields({ node: true, size: true }).exec(res => {
      if (!res[0] || !res[0].node || !res[0].width) {
        if (retry < 3) {
          setTimeout(() => this.drawCanvas(selector, drawFn, retry + 1), 80)
        }
        return
      }
      const canvas = res[0].node
      const ctx = canvas.getContext('2d')
      const { width, height } = setupCanvas2d(canvas, ctx, res[0].width, res[0].height)
      drawFn(ctx, width, height)
    })
  },

  onTrendPeriodTap(e) {
    const days = Number(e.currentTarget.dataset.days) || 10
    if (days === this.data.trendDays) return
    this.setData({ trendDays: days }, () => this.drawTrend())
  },

  drawTrend() {
    const colors = getChartColors(this.data.uiTheme)
    this.drawCanvas('#trendCanvas', (ctx, w, h) => {
      const days = this.data.trendDays || 10
      const hist = this.data.historyList || []
      let trend = hist.length
        ? hist.slice(0, days).slice().reverse().map(item => ({
          date: item.date,
          score: Number(item.score) || 0,
        }))
        : (this.data.trend || []).slice(-days)
      const snap = v => Math.round(v * 2) / 2
      const font = '-apple-system, BlinkMacSystemFont, PingFang SC, sans-serif'
      ctx.clearRect(0, 0, w, h)
      if (!trend || !trend.length) {
        ctx.fillStyle = colors.textMuted
        ctx.font = `12px ${font}`
        ctx.textAlign = 'center'
        ctx.textBaseline = 'middle'
        ctx.fillText('暂无趋势数据', snap(w / 2), snap(h / 2))
        return
      }

      const padL = 28
      const padR = 8
      const padT = 22
      const padB = 28
      const n = trend.length
      const chartW = w - padL - padR
      const chartH = h - padT - padB
      const barGap = n > 12 ? 3 : 5
      const barW = Math.max(6, snap((chartW - barGap * (n - 1)) / n))

      // grid lines + y轴刻度
      for (let i = 0; i <= 4; i++) {
        const y = snap(padT + (chartH / 4) * i)
        ctx.strokeStyle = colors.grid
        ctx.lineWidth = 1
        ctx.beginPath()
        ctx.moveTo(padL, y)
        ctx.lineTo(w - padR, y)
        ctx.stroke()
        ctx.fillStyle = colors.textMuted
        ctx.font = `9px ${font}`
        ctx.textAlign = 'right'
        ctx.textBaseline = 'middle'
        ctx.fillText(String(100 - i * 25), padL - 4, y)
      }

      // bars
      trend.forEach((item, i) => {
        const barX = snap(padL + i * (barW + barGap))
        const barH = Math.max(4, snap((Math.max(0, Math.min(100, item.score)) / 100) * chartH))
        const barY = snap(padT + chartH - barH)
        const r = Math.min(3, barW / 2)

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

        // score label：bar 够高时内嵌，否则顶部外显
        if (barH >= 14) {
          ctx.fillStyle = 'rgba(255,255,255,0.92)'
          ctx.font = `9px ${font}`
          ctx.textAlign = 'center'
          ctx.textBaseline = 'top'
          ctx.fillText(String(item.score), barX + barW / 2, barY + 2)
        } else if (item.score > 0) {
          ctx.fillStyle = colors.textPrimary || '#0f172a'
          ctx.font = `600 9px ${font}`
          ctx.textAlign = 'center'
          ctx.textBaseline = 'bottom'
          ctx.fillText(String(item.score), barX + barW / 2, barY - 2)
        }

        // 日期标签：稀疏显示（≤8根全显，>8根只显首尾及每隔几根）
        const showDate = n <= 8 || i === 0 || i === n - 1 || i % Math.max(1, Math.ceil(n / 6)) === 0
        if (showDate) {
          const dateLabel = (item.date || '').slice(5).replace('-', '/')
          ctx.fillStyle = colors.textMuted
          ctx.font = `9px ${font}`
          ctx.textAlign = 'center'
          ctx.textBaseline = 'top'
          ctx.fillText(dateLabel, barX + barW / 2, padT + chartH + 6)
        }
      })
    })
  },

  goDetail() {
    if (this.data.scoreCalculating) return
    wx.navigateTo({ url: '/pages/detail/detail' })
  },

  goAuctionDetail() {
    wx.navigateTo({ url: '/pages/auction/auction' })
  },

  resolveShareScore() {
    const display = Number(this.data.displayScore)
    if (!Number.isNaN(display) && this.data.displayScore !== '') return display
    return Number(this.data.score) || 0
  },

  onSharePoster() {
    if (this.data.scoreCalculating || this._sharingPoster) return
    this._sharingPoster = true
    wx.showLoading({ title: '生成海报', mask: true })
    createSharePoster({
      score: this.resolveShareScore(),
      levelLabel: this.data.levelLabel,
      levelClass: this.data.levelClass,
      positionDesc: this.data.positionDesc,
      dailyQuoteText: this.data.dailyQuoteText,
      dailyQuoteAuthor: this.data.dailyQuoteAuthor,
      generatedAt: this.data.generatedAt,
      indicatorSections: this.data.indicatorSections
    })
      .then(path => {
        wx.hideLoading()
        this.setData({
          sharePosterVisible: true,
          sharePosterPath: path
        })
      })
      .catch(() => {
        wx.hideLoading()
        wx.showToast({ title: '海报生成失败', icon: 'none' })
      })
      .finally(() => {
        this._sharingPoster = false
      })
  },

  onCloseSharePoster() {
    this.setData({
      sharePosterVisible: false,
      sharePosterPath: '',
      sharePosterSaving: false,
      sharePosterForwarding: false
    })
  },

  onSaveSharePoster() {
    const path = this.data.sharePosterPath
    if (!path || this.data.sharePosterSaving) return
    this.setData({ sharePosterSaving: true })
    savePosterToAlbum(path)
      .then(() => {
        this.onCloseSharePoster()
        wx.showToast({ title: '已保存到相册', icon: 'success' })
      })
      .catch(err => {
        const msg = String((err && err.errMsg) || (err && err.message) || '')
        if (!msg.includes('auth') && !msg.includes('cancel')) {
          wx.showToast({ title: '保存失败，请重试', icon: 'none' })
        }
      })
      .finally(() => {
        this.setData({ sharePosterSaving: false })
      })
  },

  onForwardSharePoster() {
    const path = this.data.sharePosterPath
    if (!path || this.data.sharePosterForwarding) return
    this.setData({ sharePosterForwarding: true })
    this.onCloseSharePoster()

    forwardPosterImage(path)
      .catch(err => {
        const msg = String((err && err.errMsg) || (err && err.message) || '')
        if (!msg.includes('cancel')) {
          wx.showToast({ title: '转发失败，请重试', icon: 'none' })
        }
      })
      .finally(() => {
        this.setData({ sharePosterForwarding: false })
      })
  },
})
