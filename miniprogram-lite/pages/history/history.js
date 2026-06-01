const { fetchHistory } = require('../../utils/store')
const { formatErrMsg } = require('../../utils/errMsg')
const { formatHeaderDate, calcStreak } = require('../../utils/verdict')
const { getScoreColor } = require('../../utils/scoreColor')

const PERIODS = [
  { days: 5, label: '近5日' },
  { days: 10, label: '近10日' },
  { days: 20, label: '近20日' },
]

const WEEKDAYS = ['日', '一', '二', '三', '四', '五', '六']

function buildCalendar(list, year, month) {
  const dateMap = {}
  for (const item of list || []) {
    const key = String(item.fullDate || '').slice(0, 10)
    if (key) dateMap[key] = item
  }
  const pad = n => String(n).padStart(2, '0')
  const daysInMonth = new Date(year, month, 0).getDate()
  let startWd = new Date(year, month - 1, 1).getDay() // Sun=0, Mon=1 ... Sat=6

  const today = new Date()
  const todayStr = `${today.getFullYear()}-${pad(today.getMonth()+1)}-${pad(today.getDate())}`

  const cells = []
  for (let i = 0; i < startWd; i++) cells.push({ empty: true })
  for (let d = 1; d <= daysInMonth; d++) {
    const ds = `${year}-${pad(month)}-${pad(d)}`
    const item = dateMap[ds]
    const score = item ? (item.score || 0) : 0
    const key = item && item.verdict ? item.verdict.key : ''
    cells.push({
      empty: false,
      day: d,
      isToday: ds === todayStr,
      hasData: !!item,
      verdictKey: key,
      color: item ? getScoreColor(score) : '',
      score: item ? score : null,
    })
  }
  while (cells.length % 7 !== 0) cells.push({ empty: true })
  return cells
}

function buildTrendBars(fullList, days) {
  const slice = (fullList || []).slice(0, days).slice().reverse()
  const maxScore = Math.max(...slice.map(i => Number(i.score) || 0), 1)
  return slice.map(item => {
    const score = Number(item.score) || 0
    const key = score >= 70 ? 'long' : score >= 30 ? 'mid' : 'empty'
    const color = key === 'long' ? '#e63838' : key === 'mid' ? '#f59e0b' : '#91d1ed'
    const dateStr = String(item.date || '')
    return {
      date: item.date,
      fullDate: item.date,
      score,
      heightPct: Math.round((score / maxScore) * 100),
      color,
      verdictKey: key,
      verdict: { key, emoji: key === 'long' ? '🔴' : key === 'mid' ? '🟡' : '🔵' },
      weatherLine: item.weatherLine || '',
      dateLabel: dateStr.length >= 10 ? dateStr.slice(5).replace('-', '/') : dateStr,
      isToday: false,
    }
  })
}

function calcSummary(list) {
  const recent = (list || []).slice(0, 10)
  let long = 0, mid = 0, empty = 0
  for (const item of recent) {
    const key = item.verdict && item.verdict.key
    if (key === 'long') long++
    else if (key === 'empty') empty++
    else mid++
  }
  return { long, mid, empty, total: recent.length }
}

Page({
  data: {
    loading: true,
    error: '',
    list: [],
    trendBars: [],
    headerDate: formatHeaderDate(),
    trendDays: 10,
    periods: PERIODS,
    summary: null,
    streakText: '',
    viewMode: 'calendar',   // 'chart' | 'calendar'
    weekdays: WEEKDAYS,
    calYear: 0,
    calMonth: 0,
    calTitle: '',
    calCells: [],
  },

  onLoad() {
    const now = new Date()
    this.setData({ calYear: now.getFullYear(), calMonth: now.getMonth() + 1 })
    this.loadData().catch(() => {})
  },

  onPullDownRefresh() {
    this.loadData(true).finally(() => wx.stopPullDownRefresh())
  },

  loadData(force) {
    if (!force && this._loading) return this._loading
    this.setData({ loading: true, error: '' })
    this._loading = fetchHistory(30)
      .then(list => {
        this._fullList = list || []
        const summary = calcSummary(this._fullList)
        const streak = calcStreak(this._fullList)
        const { calYear, calMonth } = this.data
        const VERDICT_COLOR = { long: '#cf1322', mid: '#faad14', empty: '#38bdf8' }
        const listWithColor = this._fullList.map(item => {
          const key = item.verdict && item.verdict.key
          const color = item.score > 0
            ? getScoreColor(item.score)
            : (VERDICT_COLOR[key] || '#94a3b8')
          return {
            date: item.date,
            fullDate: item.fullDate,
            score: item.score,
            verdictKey: key,
            emoji: item.verdict && item.verdict.emoji,
            weatherLine: item.weatherLine,
            color,
          }
        })
        this.setData({
          loading: false,
          list: listWithColor,
          trendBars: buildTrendBars(this._fullList, this.data.trendDays),
          summary,
          streakText: streak ? `已连续 ${streak.count} 天${streak.label}` : '',
          calCells: buildCalendar(this._fullList, calYear, calMonth),
          calTitle: `${calYear}年${calMonth}月`,
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
    this.setData({
      trendDays: days,
      trendBars: buildTrendBars(this._fullList || this.data.list, days),
    })
  },

  onViewToggle(e) {
    const mode = e.currentTarget.dataset.mode
    if (mode === this.data.viewMode) return
    this.setData({ viewMode: mode })
  },

  onCalPrev() {
    let { calYear, calMonth } = this.data
    calMonth--
    if (calMonth < 1) { calMonth = 12; calYear-- }
    const cells = buildCalendar(this._fullList || [], calYear, calMonth)
    this.setData({ calYear, calMonth, calTitle: `${calYear}年${calMonth}月`, calCells: cells })
  },

  onCalNext() {
    let { calYear, calMonth } = this.data
    const now = new Date()
    if (calYear >= now.getFullYear() && calMonth >= now.getMonth() + 1) return
    calMonth++
    if (calMonth > 12) { calMonth = 1; calYear++ }
    const cells = buildCalendar(this._fullList || [], calYear, calMonth)
    this.setData({ calYear, calMonth, calTitle: `${calYear}年${calMonth}月`, calCells: cells })
  },
})
