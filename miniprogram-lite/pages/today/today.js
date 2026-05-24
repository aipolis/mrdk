const { fetchToday, fetchTrend, loadCachedToday } = require('../../utils/store')
const { requestDailySubscribe } = require('../../utils/subscribe')
const { APP_TITLE, APP_SUBTITLE, QUOTE_SECTION } = require('../../utils/config')
const { formatHeaderDate, LONG, MID, EMPTY } = require('../../utils/verdict')
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
    quoteSection: QUOTE_SECTION,
    headerDate: '',
    updateBadge: '',
    live: false,
    verdictKey: 'mid',
    verdictChar: '中',
    weatherText: '多云',
    weatherShort: '多云',
    actionText: '带伞',
    weatherLine: '多云 · 带伞',
    heroIcon: MID.heroIcon,
    score: 0,
    displayScore: 25,
    themeClass: 'weather-mid',
    pageReady: false,
    trendBars: [],
    verdictTabs: VERDICT_TABS,
    subscribed: false,
  },

  onLoad() {
    this.setData({
      headerDate: formatHeaderDate(),
      subscribed: !!wx.getStorageSync('subscribe_sentimentDaily'),
    })
    const cached = loadCachedToday()
    if (cached) this.applyData(cached)
    this.loadData().catch(() => {})
  },

  onShow() {
    this.setData({
      headerDate: formatHeaderDate(),
      subscribed: !!wx.getStorageSync('subscribe_sentimentDaily'),
    })
  },

  onPullDownRefresh() {
    this.loadData(true).finally(() => wx.stopPullDownRefresh())
  },

  applyData(data) {
    const v = data.verdict || {}
    this.setData({
      loading: false,
      error: '',
      headerDate: formatHeaderDate(),
      updateBadge: data.updateBadge || '',
      live: !!data.live,
      verdictKey: v.key || 'mid',
      verdictChar: v.char || '中',
      weatherText: v.weather || '',
      weatherShort: data.weatherShort || v.weatherShort || '',
      actionText: v.action || '',
      weatherLine: data.weatherLine || '',
      heroIcon: data.heroIcon || v.heroIcon || v.icon || MID.heroIcon,
      score: data.score != null ? data.score : 0,
      displayScore: data.useLiveScore ? (data.score != null ? data.score : 0) : 25,
      themeClass: data.useLiveScore ? (v.themeClass || 'weather-mid') : (25 > 70 ? 'weather-long' : 25 >= 30 ? 'weather-mid' : 'weather-empty'),
      pageReady: true,
      trendBars: data.trendBars || this.data.trendBars,
    })
    this._todayRaw = data.raw
  },

  loadData(force) {
    if (!force && this._loading) return this._loading
    if (force || !this.data.pageReady) this.setData({ loading: true, error: '' })

    this._loading = fetchToday()
      .then(data => {
        this.applyData(data)
        return fetchTrend(10, data.raw).then(bars => {
          this.setData({ trendBars: bars })
        })
      })
      .catch(err => {
        const msg = formatErrMsg(err, '加载失败，请下拉刷新')
        if (!this._todayRaw && !loadCachedToday()) {
          this.setData({ loading: false, error: msg })
        } else {
          this.setData({ loading: false })
          wx.showToast({ title: '更新失败', icon: 'none' })
        }
      })
      .finally(() => {
        this._loading = null
      })
    return this._loading
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
})
