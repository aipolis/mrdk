/** 本地日历日期与情绪分时间展示 */

function pad2(n) {
  return String(n).padStart(2, '0')
}

function getLocalCalendarKey(d = new Date()) {
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`
}

function getLocalNowHm(d = new Date()) {
  return `${pad2(d.getHours())}:${pad2(d.getMinutes())}`
}

const WEEKDAYS = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']

function parseDateKey(dateStr) {
  if (!dateStr) return null
  const parts = String(dateStr).split('-')
  if (parts.length !== 3) return null
  const dt = new Date(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]))
  if (Number.isNaN(dt.getTime())) return null
  return {
    key: `${parts[0]}-${pad2(parts[1])}-${pad2(parts[2])}`,
    month: Number(parts[1]),
    day: Number(parts[2]),
    weekday: WEEKDAYS[dt.getDay()],
    ts: dt.getTime()
  }
}

function formatDisplayDate(dateStr) {
  const parsed = parseDateKey(dateStr)
  if (!parsed) return dateStr || ''
  return `${parsed.month}月${parsed.day}日 ${parsed.weekday}`
}

function formatHeaderDate() {
  return formatDisplayDate(getLocalCalendarKey())
}

/** 相对自然日：今日 / 昨日 / 前天 / M月D日 */
function relativeDayLabel(dateStr, todayKey = getLocalCalendarKey()) {
  const ref = parseDateKey(dateStr)
  const today = parseDateKey(todayKey)
  if (!ref) return '今日'
  if (!today) return `${ref.month}月${ref.day}日`
  if (ref.key === today.key) return '今日'
  const diffDays = Math.round((today.ts - ref.ts) / 86400000)
  if (diffDays === 1) return '昨日'
  if (diffDays === 2) return '前天'
  return `${ref.month}月${ref.day}日`
}

/** 展示分最后一次形成时间，如「昨日 15:00 更新」「盘中 14:35 更新」 */
function formatGaugeUpdatedAt(data) {
  if (!data) return '更新中'
  const label = data.generatedAtLabel || data.generatedAt
  if (label && String(label).includes('更新')) {
    return String(label)
  }
  const refDate = data.refDate || data.adviceDate || data.date
  const dayLabel = relativeDayLabel(refDate)
  const hm = data.generatedAtTime || '15:00'
  return `${dayLabel} ${hm} 更新`
}

module.exports = {
  getLocalCalendarKey,
  getLocalNowHm,
  parseDateKey,
  formatDisplayDate,
  formatHeaderDate,
  relativeDayLabel,
  formatGaugeUpdatedAt,
  WEEKDAYS
}
