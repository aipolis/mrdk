const { getScoreColor } = require('./scoreColor')

function formatBarDate(date) {
  const s = String(date || '')
  if (s.length >= 10) return s.slice(5).replace('-', '/')
  if (s.length === 8) return `${s.slice(4, 6)}/${s.slice(6, 8)}`
  return s
}

function mapTrendBars(list, todayItem, count = 10) {
  const seen = new Set()
  const rows = []
  const todayDate = todayItem ? String(todayItem.date || todayItem.fullDate || '') : ''

  const push = (item, isToday) => {
    const fullDate = String(item.date || item.fullDate || '')
    if (!fullDate || seen.has(fullDate)) return
    seen.add(fullDate)
    const score = Number(item.score != null ? item.score : item.displayScore) || 0
    const color = getScoreColor(score, item.levelClass, item.levelColor)
    const verdictKey = score > 70 ? 'long' : score < 30 ? 'empty' : 'mid'
    rows.push({
      score,
      color,
      verdictKey,
      dateLabel: formatBarDate(fullDate),
      fullDate,
      heightPct: Math.max(8, Math.min(100, score)),
      isToday: isToday || fullDate === todayDate,
    })
  }

  if (todayItem) push(todayItem, true)
  ;(list || []).forEach(item => push(item, false))

  const bars = rows.slice(0, count).reverse()
  return bars
}

module.exports = { mapTrendBars, formatBarDate }
