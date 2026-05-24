const { fetchHistory, fetchTrend } = require('../../utils/store')
const { formatErrMsg } = require('../../utils/errMsg')
const { formatHeaderDate } = require('../../utils/verdict')

const PERIODS = [
  { days: 5, label: '近5日' },
  { days: 10, label: '近10日' },
  { days: 20, label: '近20日' },
]

Page({
  data: {
    loading: true,
    error: '',
    list: [],
    trendBars: [],
    headerDate: formatHeaderDate(),
    trendDays: 10,
    periods: PERIODS,
  },

  onLoad() {
    this.loadData().catch(() => {})
  },

  onPullDownRefresh() {
    this.loadData(true).finally(() => wx.stopPullDownRefresh())
  },

  loadData(force) {
    if (!force && this._loading) return this._loading
    this.setData({ loading: true, error: '' })
    this._loading = Promise.all([
      fetchHistory(30),
      fetchTrend(this.data.trendDays),
    ])
      .then(([list, bars]) => {
        this.setData({
          loading: false,
          list: list || [],
          trendBars: bars || [],
        })
      })
      .catch(err => {
        this.setData({
          loading: false,
          error: formatErrMsg(err, '加载失败'),
        })
      })
      .finally(() => {
        this._loading = null
      })
    return this._loading
  },

  onPeriodTap(e) {
    const days = Number(e.currentTarget.dataset.days) || 10
    if (days === this.data.trendDays) return
    this.setData({ trendDays: days })
    fetchTrend(days).then(bars => {
      this.setData({ trendBars: bars || [] })
    }).catch(() => {})
  },
})
