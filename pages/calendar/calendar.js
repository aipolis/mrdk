const {
  getAllRecords,
  buildCalendar,
  getMonthStats,
  getMatchTier,
  formatShortDate
} = require('../../utils/position')

Page({
  data: {
    calendarYear: 2026,
    calendarMonth: 5,
    calendarWeeks: [],
    monthStats: {},
    selectedDay: null,
    legend: [
      { tier: 'excellent', label: '优秀 ≥80%', color: '#52C41A' },
      { tier: 'good', label: '良好 60-79%', color: '#95DE64' },
      { tier: 'average', label: '一般 40-59%', color: '#FAAD14' },
      { tier: 'poor', label: '较差 <40%', color: '#FF4D4F' },
      { tier: 'none', label: '无数据', color: '#F0F0F0' }
    ]
  },

  onLoad() {
    const now = new Date()
    this.setData({
      calendarYear: now.getFullYear(),
      calendarMonth: now.getMonth() + 1
    })
    this.refreshCalendar()
  },

  refreshCalendar() {
    const { calendarYear, calendarMonth } = this.data
    const records = getAllRecords()
    this.setData({
      calendarWeeks: buildCalendar(calendarYear, calendarMonth, records),
      monthStats: getMonthStats(calendarYear, calendarMonth, records),
      selectedDay: null
    })
  },

  onPrevMonth() {
    let { calendarYear, calendarMonth } = this.data
    calendarMonth--
    if (calendarMonth < 1) { calendarMonth = 12; calendarYear-- }
    this.setData({ calendarYear, calendarMonth }, () => this.refreshCalendar())
  },

  onNextMonth() {
    let { calendarYear, calendarMonth } = this.data
    calendarMonth++
    if (calendarMonth > 12) { calendarMonth = 1; calendarYear++ }
    this.setData({ calendarYear, calendarMonth }, () => this.refreshCalendar())
  },

  onDayTap(e) {
    const item = e.currentTarget.dataset.item
    if (!item || item.empty || !item.hasRecord) return
    const records = getAllRecords()
    const rec = records[item.date]
    if (!rec) return
    const tier = getMatchTier(rec.matchRate)
    this.setData({
      selectedDay: {
        ...rec,
        shortDate: formatShortDate(rec.date),
        tierLabel: tier.label,
        tierClass: tier.tier
      }
    })
  }
})
