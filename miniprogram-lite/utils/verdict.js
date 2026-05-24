/** 龙 / 中 / 空 → 天气文案（前端映射，后端逻辑不变） */

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

function calcVerdictFromScore(score, emptyWarning) {
  if (emptyWarning || score < 30) return EMPTY
  if (score > 70) return LONG
  return MID
}

function calcVerdict(data) {
  return calcVerdictFromScore(scoreOf(data), !!data.emptyWarning)
}

function calcHistoryVerdict(item) {
  const score = Number(item && item.score) || 0
  const level = String(item && item.levelClass || '')
  if (score <= 14 || level === 'cold' || level === 'frenzy' && score < 20) {
    return calcVerdictFromScore(score, score <= 14)
  }
  return calcVerdictFromScore(score, false)
}

function formatRefDate(data) {
  const d = (data && (data.refDate || data.adviceDate || data.date)) || ''
  return String(d).replace(/^(\d{4})(\d{2})(\d{2})$/, '$1-$2-$3')
}

function formatHeaderDate() {
  const d = new Date()
  const w = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'][d.getDay()]
  return `${d.getMonth() + 1}月${d.getDate()}日 ${w}`
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

function formatUpdateBadge(raw) {
  const label = raw.generatedAtLabel || raw.generatedAt || ''
  if (!label) return ''
  return label.includes('更新') ? `● ${label}` : `● ${label} 更新`
}

function mapHistoryList(list) {
  return (list || []).map(item => {
    const verdict = calcHistoryVerdict(item)
    const date = String(item.date || '')
    const label = date.length === 8
      ? `${date.slice(4, 6)}-${date.slice(6, 8)}`
      : date
    return {
      date: label,
      fullDate: date,
      verdict,
      weatherLine: `${verdict.weather} · ${verdict.action}`,
    }
  })
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
}
