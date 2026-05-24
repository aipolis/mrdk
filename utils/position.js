const STORAGE_KEY = 'positionRecords'
const USAGE_KEY = 'firstUseDate'
const TOLERANCE = 10

const RISK_FACTOR = {
  conservative: 0.7,
  steady: 1.0,
  aggressive: 1.2
}

const ENCOURAGE = {
  excellent: [
    '今日持仓记录与情绪区间较为一致，已存档供个人复盘。',
    '个人复盘：持仓与情绪数据匹配度较高。',
    '记录完整，可供后续回顾对照。'
  ],
  good: [
    '整体记录尚可，与情绪区间大致吻合。',
    '复盘数据已保存，可继续完善记录习惯。'
  ],
  average: [
    '持仓记录与情绪区间存在一定偏差，供本人回顾。',
    '还有提升空间，可结合情绪指标复盘。'
  ],
  poor: [
    '持仓记录与情绪区间偏差较大，仅供个人复盘参考。',
    '可回顾当日情绪分，完善个人交易日志。',
    '记录已保存，不构成任何操作评价。'
  ]
}

const ADVICE_TEXT = {
  excellent: '个人持仓与市场情绪区间匹配度较高，仅供本人复盘参考。',
  good: '持仓记录整体合理，与情绪区间略有不符，供个人复盘。',
  average: '持仓记录与情绪区间偏差偏大，仅供个人复盘对照。',
  poor: '持仓记录与情绪区间差距较大，仅为个人日志，不构成任何操作建议。'
}

function formatDate(d = new Date()) {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

function formatShortDate(dateStr) {
  return dateStr ? dateStr.slice(5) : ''
}

function getSuggestedPercent(score, riskLevel = 'steady') {
  const { getPositionAdvice } = require('./data')
  const base = getPositionAdvice(score).percent
  const factor = RISK_FACTOR[riskLevel] || 1
  return Math.min(100, Math.round(base * factor))
}

function calcMatchRate(actualPercent, suggestedPercent) {
  const diff = Math.abs(actualPercent - suggestedPercent)
  return Math.max(0, Math.min(100, 100 - diff * 5))
}

function getMatchTier(matchRate) {
  if (matchRate >= 80) return { tier: 'excellent', label: '优秀', color: '#52C41A', emoji: '😊' }
  if (matchRate >= 60) return { tier: 'good', label: '良好', color: '#95DE64', emoji: '🙂' }
  if (matchRate >= 40) return { tier: 'average', label: '一般', color: '#FAAD14', emoji: '😐' }
  return { tier: 'poor', label: '较差', color: '#FF4D4F', emoji: '😟' }
}

function getAllRecords() {
  return wx.getStorageSync(STORAGE_KEY) || {}
}

function saveRecord(record) {
  const all = getAllRecords()
  all[record.date] = record
  wx.setStorageSync(STORAGE_KEY, all)
  return all
}

function evaluatePosition(actualPercent, suggestedPercent) {
  const diff = Math.abs(actualPercent - suggestedPercent)
  const matchRate = calcMatchRate(actualPercent, suggestedPercent)
  const tierInfo = getMatchTier(matchRate)
  const matched = diff <= TOLERANCE
  const stockPercent = actualPercent
  const cashPercent = 100 - actualPercent

  const msgs = ENCOURAGE[tierInfo.tier] || ENCOURAGE.poor
  const message = msgs[Math.floor(Math.random() * msgs.length)]
  const advice = ADVICE_TEXT[tierInfo.tier] || ADVICE_TEXT.poor

  return {
    matched,
    rating: tierInfo.label,
    level: tierInfo.tier,
    tier: tierInfo.tier,
    badge: tierInfo.emoji,
    diff,
    matchRate,
    score: matchRate,
    stockPercent,
    cashPercent,
    message,
    advice,
    exceedPercent: Math.min(99, Math.max(50, matchRate - 5))
  }
}

function getUsageDays() {
  let first = wx.getStorageSync(USAGE_KEY)
  if (!first) {
    first = formatDate()
    wx.setStorageSync(USAGE_KEY, first)
  }
  const start = new Date(first.replace(/-/g, '/'))
  const now = new Date()
  const days = Math.floor((now - start) / 86400000) + 1
  return Math.max(1, days)
}

function getStats(records, days = 30) {
  const cutoff = new Date()
  cutoff.setDate(cutoff.getDate() - days)
  const cutoffStr = formatDate(cutoff)

  const list = Object.values(records)
    .filter(r => r.date >= cutoffStr)
    .sort((a, b) => b.date.localeCompare(a.date))

  const total = list.length
  const matched = list.filter(r => r.matched).length
  const excellent = list.filter(r => r.tier === 'excellent' || r.level === 'excellent').length
  const avgMatchRate = total
    ? Math.round(list.reduce((s, r) => s + (r.matchRate || calcMatchRate(r.actualPercent, r.suggestedPercent)), 0) / total)
    : 0

  let streak = 0
  for (const r of list) {
    if (r.matched) streak++
    else break
  }

  const winRate = total ? Math.round((excellent / total) * 100) : 0

  return {
    total,
    matched,
    excellent,
    matchRate: total ? Math.round((matched / total) * 100) : 0,
    avgMatchRate,
    streak,
    winRate,
    disciplineScore: avgMatchRate
  }
}

function getWeeklyTrajectory(records) {
  const result = []
  for (let i = 6; i >= 0; i--) {
    const d = new Date()
    d.setDate(d.getDate() - i)
    const dateStr = formatDate(d)
    const rec = records[dateStr]
    result.push({
      date: formatShortDate(dateStr),
      fullDate: dateStr,
      percent: rec ? rec.actualPercent : null,
      matchRate: rec ? (rec.matchRate || calcMatchRate(rec.actualPercent, rec.suggestedPercent)) : null
    })
  }
  return result
}

function getRecentMatchRates(records, days = 7) {
  const result = []
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date()
    d.setDate(d.getDate() - i)
    const dateStr = formatDate(d)
    const rec = records[dateStr]
    result.push({
      date: formatShortDate(dateStr),
      matchRate: rec ? (rec.matchRate || calcMatchRate(rec.actualPercent, rec.suggestedPercent)) : 0,
      hasRecord: !!rec
    })
  }
  return result
}

function buildCalendar(year, month, records) {
  const firstDay = new Date(year, month - 1, 1)
  const daysInMonth = new Date(year, month, 0).getDate()
  const startWeekday = firstDay.getDay()

  const weeks = []
  let week = []

  for (let i = 0; i < startWeekday; i++) week.push({ empty: true })

  for (let d = 1; d <= daysInMonth; d++) {
    const dateStr = `${year}-${String(month).padStart(2, '0')}-${String(d).padStart(2, '0')}`
    const rec = records[dateStr]
    const matchRate = rec
      ? (rec.matchRate || calcMatchRate(rec.actualPercent, rec.suggestedPercent))
      : null
    const tierInfo = rec ? getMatchTier(matchRate) : null

    week.push({
      day: d,
      date: dateStr,
      empty: false,
      hasRecord: !!rec,
      matched: rec ? rec.matched : null,
      matchRate,
      tier: tierInfo ? tierInfo.tier : 'none',
      tierLabel: tierInfo ? tierInfo.label : '',
      rating: rec ? rec.rating : '',
      actual: rec ? rec.actualPercent : null,
      suggested: rec ? rec.suggestedPercent : null
    })
    if (week.length === 7) {
      weeks.push(week)
      week = []
    }
  }

  if (week.length) {
    while (week.length < 7) week.push({ empty: true })
    weeks.push(week)
  }
  return weeks
}

function getMonthStats(year, month, records) {
  const prefix = `${year}-${String(month).padStart(2, '0')}`
  const monthRecords = Object.values(records).filter(r => r.date.startsWith(prefix))
  const total = monthRecords.length
  const matched = monthRecords.filter(r => r.matched).length
  const excellent = monthRecords.filter(r => (r.tier || r.level) === 'excellent').length
  const avgMatchRate = total
    ? Math.round(monthRecords.reduce((s, r) => s + (r.matchRate || 0), 0) / total)
    : 0
  const winRate = total ? Math.round((excellent / total) * 100) : 0

  return { total, matched, excellent, rate: total ? Math.round((matched / total) * 100) : 0, avgMatchRate, winRate }
}

function buildRecordPayload(today, actualPercent, suggestedPercent, uploadImage) {
  const result = evaluatePosition(actualPercent, suggestedPercent)
  return {
    date: today,
    actualPercent,
    suggestedPercent,
    stockPercent: result.stockPercent,
    cashPercent: result.cashPercent,
    matched: result.matched,
    rating: result.rating,
    level: result.level,
    tier: result.tier,
    badge: result.badge,
    diff: result.diff,
    matchRate: result.matchRate,
    score: result.score,
    message: result.message,
    advice: result.advice,
    exceedPercent: result.exceedPercent,
    imagePath: uploadImage,
    timestamp: Date.now()
  }
}

module.exports = {
  STORAGE_KEY,
  TOLERANCE,
  formatDate,
  formatShortDate,
  getSuggestedPercent,
  getAllRecords,
  saveRecord,
  evaluatePosition,
  calcMatchRate,
  getMatchTier,
  getUsageDays,
  getStats,
  getWeeklyTrajectory,
  getRecentMatchRates,
  buildCalendar,
  getMonthStats,
  buildRecordPayload
}
