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

/** 情绪分旁：数据实际更新时间，如「昨日 15:00 更新」 */
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

/**
 * 状态栏语义文字（与 web buildStatusText 逻辑一致）
 * scoreMode=live  → "今日实时情绪 · HH:MM 更新"
 * ref != advice, advice=today  → "昨日收盘情绪 · 今日参考"
 * ref == advice == today        → "今日收盘情绪 · 明日参考"
 * advice 是未来                  → "昨日收盘情绪 · N月D日参考"
 */
function buildStatusText(data) {
  if (!data) return '数据加载中…'
  const scoreMode = data.scoreMode || 'baseline'
  const updTime = data.generatedAtTime || ''
  if (scoreMode === 'live') {
    return `今日实时情绪${updTime ? ' · ' + updTime + ' 更新' : ''}`
  }
  const todayKey = getLocalCalendarKey()
  function dateKey(raw) {
    if (!raw) return ''
    return String(raw).replace(/\D/g, '').slice(0, 8)
  }
  const refKey = dateKey(data.refDate)
  const advKey = dateKey(data.adviceDate || data.date)
  // 从 generatedAtLabel 提取 ref 日描述
  const genLabel = String(data.generatedAtLabel || data.generatedAt || '')
  const dayWord = (genLabel.match(/^(今天|昨天|前天)/) || [])[1]
  const refLabel = dayWord ? dayWord.replace('天', '日') : relativeDayLabel(data.refDate)
  const todayDKey = dateKey(todayKey)
  if (refKey && refKey === advKey && advKey === todayDKey) return '今日收盘情绪 · 明日参考'
  if (advKey === todayDKey) return `${refLabel}收盘情绪 · 今日参考`
  // 未来日期
  const advParsed = parseDateKey(data.adviceDate || data.date)
  const advLabel = advParsed ? `${advParsed.month}月${advParsed.day}日` : '下一交易日'
  return `${refLabel}收盘情绪 · ${advLabel}参考`
}

module.exports = {
  getLocalCalendarKey,
  getLocalNowHm,
  parseDateKey,
  formatDisplayDate,
  formatHeaderDate,
  relativeDayLabel,
  formatGaugeUpdatedAt,
  buildStatusText,
  WEEKDAYS
}
