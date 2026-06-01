const { getAuctionDetail } = require('../../utils/api')
const uiThemeBehavior = require('../../behaviors/uiTheme')

const TABS = [
  { id: 'oneWord', label: '竞价一字' },
  { id: 'topSectors', label: '板块Top10' },
  { id: 'volumeSurge', label: '量能异动' },
]

Page({
  behaviors: [uiThemeBehavior],

  data: {
    loading: true,
    volumeLoading: false,
    error: '',
    ready: false,
    updatedAt: '',
    tradeDate: '',
    activeTab: 'oneWord',
    tabs: TABS,
    oneWordStocks: [],
    topSectors: [],
    volumeSurgeStocks: [],
    volumeSurgeSectors: [],
    topSectorsReady: false,
    volumeSurgeReady: false,
    sourceNote: '',
    volumeLoaded: false,
  },

  _inVolumeSurgeLiveWindow(now = new Date()) {
    const hm = now.getHours() * 60 + now.getMinutes()
    return hm >= 9 * 60 + 20 && hm < 9 * 60 + 26
  },

  _getPollIntervalMs() {
    const now = new Date()
    const hm = now.getHours() * 60 + now.getMinutes()
    if (hm >= 9 * 60 + 15 && hm < 9 * 60 + 26) return 20000
    return 0
  },

  _getVolumePollIntervalMs() {
    if (this._inVolumeSurgeLiveWindow()) return 30000
    return 0
  },

  _schedulePoll() {
    if (this._pollTimer) {
      clearTimeout(this._pollTimer)
      this._pollTimer = null
    }
    const ms = this._getPollIntervalMs()
    if (!ms) return
    this._pollTimer = setTimeout(() => {
      this.loadDetail(this._date, { refresh: true, silent: true })
      this._schedulePoll()
    }, ms)
  },

  _scheduleVolumePoll() {
    if (this._volumePollTimer) {
      clearTimeout(this._volumePollTimer)
      this._volumePollTimer = null
    }
    const volMs = this._getVolumePollIntervalMs()
    if (!volMs) return
    this._volumePollTimer = setTimeout(() => {
      this.loadVolumeSurge(this._date, { refresh: true })
      this._scheduleVolumePoll()
    }, volMs)
  },

  _stopPoll() {
    if (this._pollTimer) {
      clearTimeout(this._pollTimer)
      this._pollTimer = null
    }
    if (this._volumePollTimer) {
      clearTimeout(this._volumePollTimer)
      this._volumePollTimer = null
    }
  },

  onUnload() {
    this._stopPoll()
  },

  onLoad(options) {
    const date = options.date || ''
    this._date = date
    this._volumeRequested = false
    this.loadDetail(date)
    this._schedulePoll()
    this._scheduleVolumePoll()
  },

  onPullDownRefresh() {
    this.loadDetail(this._date, { refresh: true })
  },

  loadDetail(date, options = {}) {
    if (!options.refresh && !options.silent) {
      this.setData({ loading: true, error: '', volumeLoaded: false })
      this._volumeRequested = false
    }
    getAuctionDetail(date, 'oneWord,topSectors')
      .then((data) => {
        this.setData({
          loading: false,
          ready: !!data.ready,
          updatedAt: data.updatedAt || '',
          tradeDate: data.tradeDate || '',
          oneWordStocks: data.oneWordStocks || [],
          topSectors: data.topSectors || [],
          topSectorsReady: !!data.topSectorsReady,
          sourceNote: data.sourceNote || '',
          error: data.ready ? '' : '竞价数据等待 9:15 后更新',
        })
        this.loadVolumeSurge(date, { refresh: options.refresh })
      })
      .catch((err) => {
        this.setData({
          loading: false,
          error: (err && err.message) || '加载失败',
        })
      })
      .finally(() => {
        wx.stopPullDownRefresh()
      })
  },

  loadVolumeSurge(date, options = {}) {
    const live = this._inVolumeSurgeLiveWindow()
    if (!options.refresh && !live && (this.data.volumeLoaded || this.data.volumeLoading)) return
    if (this.data.volumeLoading) return
    this._volumeRequested = true
    this.setData({ volumeLoading: true })
    getAuctionDetail(date, 'volumeSurge')
      .then((data) => {
        this.setData({
          volumeSurgeStocks: data.volumeSurgeStocks || [],
          volumeSurgeSectors: data.volumeSurgeSectors || [],
          volumeSurgeReady: !!data.volumeSurgeReady,
          volumeLoaded: !!data.volumeSurgeReady || !live,
          volumeLoading: false,
        })
      })
      .catch(() => {
        this.setData({ volumeLoading: false })
      })
  },

  onTabTap(e) {
    const id = e.currentTarget.dataset.id
    if (!id || id === this.data.activeTab) return
    this.setData({ activeTab: id })
    if (id === 'volumeSurge') {
      this.loadVolumeSurge(this._date)
    }
  },
})
