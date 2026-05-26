/** 龙 / 中 / 空 → 天气文案（前端映射，后端逻辑不变） */

const { formatGaugeUpdatedAt, formatHeaderDate } = require('./dateDisplay')

const LONG = {
  key: 'long',
  char: '龙',
  weather: '天气不错',
  weatherShort: '晴天',
  action: '宜出门',
  pillHint: '宜出门',
  emoji: '☀️',
  icon: '/images/weather-sun.png',
  heroIcon: '/images/weather-sun.png',
  themeClass: 'weather-long',
}

const MID = {
  key: 'mid',
  char: '中',
  weather: '多云',
  weatherShort: '多云',
  action: '带把伞',
  pillHint: '带把伞',
  emoji: '⛅',
  icon: '/images/icon-sunny.png',
  heroIcon: '/images/weather-cloud.png',
  themeClass: 'weather-mid',
}

const EMPTY = {
  key: 'empty',
  char: '空',
  weather: '下雨天',
  weatherShort: '雨天',
  action: '休息',
  pillHint: '休息',
  emoji: '🌧️',
  icon: '/images/icon-rain.png',
  heroIcon: '/images/weather-rain.png',
  themeClass: 'weather-empty',
}

const MAP = { long: LONG, mid: MID, empty: EMPTY }

function scoreOf(data) {
  if (!data) return 0
  const v = data.displayScore != null ? data.displayScore : data.score
  return Number(v) || 0
}

/** 龙 >70 · 空 <30 · 其余为中 */
function calcVerdictFromScore(score) {
  if (score < 30) return EMPTY
  if (score > 70) return LONG
  return MID
}

function calcVerdict(data) {
  return calcVerdictFromScore(scoreOf(data))
}

function calcHistoryVerdict(item) {
  const score = Number(item && item.score) || 0
  return calcVerdictFromScore(score)
}

/** 列表/走势日期：不显示年份（MM-DD 或 MM/DD） */
function formatShortDate(date) {
  const s = String(date || '')
  if (/^\d{4}-\d{2}-\d{2}$/.test(s)) return s.slice(5)
  if (s.length === 8) return `${s.slice(4, 6)}-${s.slice(6, 8)}`
  return s
}

function formatRefDate(data) {
  const d = (data && (data.refDate || data.adviceDate || data.date)) || ''
  return String(d).replace(/^(\d{4})(\d{2})(\d{2})$/, '$1-$2-$3')
}

function mapToday(raw) {
  const verdict = calcVerdict(raw)
  const quote = String(raw.dailyQuote || '买在分歧，卖在一致').replace(/[。！？；…]$/, '')
  const score = raw.displayScore != null ? raw.displayScore : (raw.score != null ? raw.score : 0)
  return {
    verdict,
    verdictKey: verdict.key,
    weatherLine: `${verdict.weather} · ${verdict.action}`,
    weatherShort: verdict.weatherShort,
    heroIcon: verdict.heroIcon || verdict.icon,
    quote: /[。！？；…]$/.test(quote) ? quote : `${quote}。`,
    refDate: formatRefDate(raw),
    headerDate: formatHeaderDate(),
    updatedAt: raw.generatedAtLabel || raw.generatedAt || '',
    updateBadge: formatUpdateBadge(raw),
    live: raw.scoreMode === 'live',
    score: Number(score) || 0,
    useLiveScore: !!raw.useLiveScore,
    raw,
  }
}

/** 展示分最后一次形成时间（用接口 generatedAt* / generatedAtTime，不用本地时钟） */
function formatUpdateBadge(raw) {
  if (!raw) return ''
  const label = formatGaugeUpdatedAt(raw)
  return label.includes('更新') ? `● ${label}` : `● ${label} 更新`
}

function mapHistoryList(list) {
  const seen = new Set()
  const rows = []
  for (const item of list || []) {
    const date = String(item.date || '')
    const dateKey = date.replace(/-/g, '').slice(0, 8)
    if (!dateKey || seen.has(dateKey)) continue
    seen.add(dateKey)
    const verdict = calcHistoryVerdict(item)
    rows.push({
      date: formatShortDate(date),
      fullDate: date,
      verdict,
      weatherLine: `${verdict.weather} · ${verdict.action}`,
    })
  }
  return rows
}

function subscribePreviewText(verdict) {
  const v = MAP[verdict && verdict.key] || verdict || MID
  return `${v.weather}，${v.action}`
}

module.exports = {
  LONG,
  MID,
  EMPTY,
  MAP,
  calcVerdict,
  calcHistoryVerdict,
  mapToday,
  mapHistoryList,
  subscribePreviewText,
  formatHeaderDate,
  formatUpdateBadge,
  formatShortDate,
}
