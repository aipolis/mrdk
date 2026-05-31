const { fetchToday, fetchTrend, loadCachedToday } = require('../../utils/store')
const { getScoreColor } = require('../../utils/scoreColor')
const { requestDailySubscribe } = require('../../utils/subscribe')
const { APP_TITLE, APP_SUBTITLE } = require('../../utils/config')
const { formatHeaderDate, formatUpdateBadge, LONG, MID, EMPTY, getDailyQuote, calcStreak, recordTodayUsage } = require('../../utils/verdict')
const { formatErrMsg } = require('../../utils/errMsg')

const VERDICT_TABS = [
  { key: 'long', char: LONG.char, actionHint: LONG.pillHint, icon: LONG.icon, pillClass: 'pill-long' },
  { key: 'mid', char: MID.char, actionHint: MID.pillHint, icon: MID.icon, pillClass: 'pill-mid' },
  { key: 'empty', char: EMPTY.char, actionHint: EMPTY.pillHint, icon: EMPTY.icon, pillClass: 'pill-empty' },
]

Page({
  data: {
    loading: true,
    error: '',
    appTitle: APP_TITLE,
    appSubtitle: APP_SUBTITLE,
    headerDate: '',
    updateBadge: '',
    live: false,
    verdictKey: 'mid',
    verdictChar: '中',
    weatherText: '多云',
    weatherShort: '多云',
    actionText: '带把伞',
    weatherLine: '多云 · 带把伞',
    heroIcon: MID.heroIcon,
    insight: MID.insight,
    score: 0,
    displayScore: 0,
    scoreColor: '#f5a60a',
    themeClass: 'weather-mid',
    pageReady: false,
    trendBars: [],
    verdictTabs: VERDICT_TABS,
    subscribed: false,
    streakText: '',
    dailyQuote: { text: '', author: '' },
    barDetail: null,
  },

  onLoad() {
    this.setData({
      headerDate: formatHeaderDate(),
      subscribed: !!wx.getStorageSync('subscribe_sentimentDaily'),
      dailyQuote: getDailyQuote(),
    })
    const cached = loadCachedToday()
    if (cached) this.applyData(cached)
    this.loadData().catch(() => {})
  },

  onShow() {
    this.setData({
      subscribed: !!wx.getStorageSync('subscribe_sentimentDaily'),
    })
    this._refreshDisplayMeta()
    this._startPolling()
  },

  onHide() {
    this._stopPolling()
  },

  onUnload() {
    this._stopPolling()
  },

  onPullDownRefresh() {
    this.loadData(true).finally(() => wx.stopPullDownRefresh())
  },

  _isTradingHours() {
    const now = new Date()
    const day = now.getDay()
    if (day === 0 || day === 6) return false
    const hm = now.getHours() * 60 + now.getMinutes()
    return hm >= 9 * 60 + 25 && hm <= 15 * 60 + 5
  },

  _startPolling() {
    this._stopPolling()
    if (!this._isTradingHours()) return
    this._pollTimer = setTimeout(() => {
      this.loadData().catch(() => {})
      this._pollInterval = setInterval(() => {
        if (!this._isTradingHours()) {
          this._stopPolling()
          return
        }
        this.loadData().catch(() => {})
      }, 120000)
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

  _refreshDisplayMeta() {
    const patch = { headerDate: formatHeaderDate() }
    if (this._todayRaw) patch.updateBadge = formatUpdateBadge(this._todayRaw)
    this.setData(patch)
  },

  applyData(data) {
    const v = data.verdict || {}
    const verdictKey = v.key || 'mid'
    recordTodayUsage(verdictKey)
    const verdictDef = verdictKey === 'long' ? LONG : verdictKey === 'empty' ? EMPTY : MID
    this.setData({
      loading: false,
      error: '',
      updateBadge: data.updateBadge || (data.raw ? formatUpdateBadge(data.raw) : ''),
      live: !!data.live,
      verdictKey,
      verdictChar: v.char || verdictDef.char,
      weatherText: v.weather || verdictDef.weather,
      weatherShort: data.weatherShort || v.weatherShort || verdictDef.weatherShort,
      actionText: v.action || verdictDef.action,
      weatherLine: data.weatherLine || '',
      heroIcon: data.heroIcon || v.heroIcon || v.icon || verdictDef.heroIcon,
      insight: verdictDef.insight,
      score: data.score != null ? data.score : 0,
      displayScore: data.score != null ? data.score : 0,
      scoreColor: getScoreColor(data.score != null ? data.score : 0),
      themeClass: v.themeClass || verdictDef.themeClass,
      pageReady: true,
      trendBars: data.trendBars || this.data.trendBars,
    })
    this._todayRaw = data.raw
    this.setData({ headerDate: formatHeaderDate() })
  },

  loadData(force) {
    if (!force && this._loading) return this._loading
    if (force || !this.data.pageReady) this.setData({ loading: true, error: '' })

    this._loading = fetchToday()
      .then(data => {
        this.applyData(data)
        fetchTrend(10, data.raw).then(bars => {
          this.setData({ trendBars: bars })
          this._loadStreak(bars)
        }).catch(() => {})
      })
      .catch(err => {
        const msg = formatErrMsg(err, '加载失败，请下拉刷新')
        if (!this._todayRaw && !loadCachedToday()) {
          this.setData({ loading: false, error: msg })
        } else {
          this.setData({ loading: false })
          wx.showToast({ title: msg, icon: 'none' })
        }
      })
      .finally(() => {
        this._loading = null
      })
    return this._loading
  },

  _loadStreak(trendBars) {
    if (!trendBars || !trendBars.length) return
    // 从 trendBars 反推历史列表（已是旧→新顺序，需要反转为新→旧）
    const reversed = trendBars.slice().reverse().map(b => ({
      verdict: { key: b.verdictKey || (b.color === '#e63838' ? 'long' : b.color === '#91d1ed' ? 'empty' : 'mid') },
    }))
    const streak = calcStreak(reversed)
    this.setData({ streakText: streak ? `已连续 ${streak.count} 天${streak.label}` : '' })
  },

  onSubscribe() {
    if (this.data.subscribed) {
      wx.showToast({ title: '已开启每日提醒', icon: 'none' })
      return
    }
    requestDailySubscribe().then(ok => {
      this.setData({ subscribed: !!ok })
    })
  },

  onShareAppMessage() {
    const line = this.data.weatherLine || '今日天气'
    return {
      title: `明日当空 · ${line}`,
      path: '/pages/today/today',
    }
  },

  onShareFriend() {
    wx.shareAppMessage({
      title: `明日当空 · ${this.data.weatherLine || '今日天气'}`,
      path: '/pages/today/today',
    })
  },

  onBarTap(e) {
    const index = Number(e.currentTarget.dataset.index)
    const bar = this.data.trendBars[index]
    if (!bar) return
    const labelMap = { long: '晴天', mid: '多云', empty: '雨天' }
    this.setData({
      barDetail: {
        fullDate: bar.fullDate,
        score: bar.score,
        color: bar.color,
        verdictLabel: labelMap[bar.verdictKey] || '多云',
      },
    })
  },

  onCloseBarDetail() {
    this.setData({ barDetail: null })
  },

  noop() {},
})
