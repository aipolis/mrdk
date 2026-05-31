/** 龙 / 中 / 空 → 天气文案（前端映射，后端逻辑不变） */

const { formatGaugeUpdatedAt, formatHeaderDate, getLocalCalendarKey } = require('./dateDisplay')

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
  insight: '昨天天气不错，出门条件好，今天宜积极行动、把握窗口。',
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
  insight: '昨天天气多云，时晴时阴，今天带好伞再出门，稳稳当当别冒进。',
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
  insight: '昨天阴雨绵绵，雨天不出门是为了晴天走更远的路，今天宜在家静待。',
}

/** 每日轮换语录（按日期 hash，同一天所有用户相同） */
const DAILY_QUOTES = [
  { text: '不怕错过，就怕做错。不出门的时候，就在家修炼。', author: '养家心法' },
  { text: '雨天不出门，是为了晴天走更远的路。耐心等待窗口期。', author: '龙空龙心法' },
  { text: '走在分歧里，稳在一致前。最怕的是比天气更着急。', author: '养家心法' },
  { text: '弱水三千，只取一瓢。精选机会，不贪多。', author: '龙空龙心法' },
  { text: '顺势而为，不与大势为敌。天气不好，少折腾。', author: '养家心法' },
  { text: '宁可错过，不可做错。雨天不出门也是一种选择。', author: '龙空龙心法' },
  { text: '知行合一，方得始终。看天气是为了更好地出门。', author: '养家心法' },
  { text: '天气不对时选择不出门，才是走得更远的道理。', author: '龙空龙心法' },
  { text: '不必求每天都有机会，识别不该出手的日子同样是本事。', author: '养家心法' },
  { text: '多一天在家歇脚，少一次淋雨受冻，好天气自会等你。', author: '龙空龙心法' },
  { text: '天气预报不是让你不出门，是让你出门前做好准备。', author: '养家心法' },
  { text: '连续雨天之后，往往是最好的晴天。等待是有价值的。', author: '龙空龙心法' },
]

function getDailyQuote() {
  const dateStr = getLocalCalendarKey()
  let hash = 0
  for (let i = 0; i < dateStr.length; i++) {
    hash = ((hash << 5) - hash) + dateStr.charCodeAt(i)
    hash |= 0
  }
  return DAILY_QUOTES[Math.abs(hash) % DAILY_QUOTES.length]
}

/** 计算近期连续相同 verdict 天数 */
function calcStreak(historyList) {
  if (!historyList || !historyList.length) return null
  const first = historyList[0]
  if (!first || !first.verdict) return null
  const key = first.verdict.key
  let count = 0
  for (const item of historyList) {
    if (!item.verdict || item.verdict.key !== key) break
    count++
  }
  if (count < 2) return null
  const label = key === 'long' ? '晴天' : key === 'mid' ? '多云' : '雨天'
  return { count, key, label }
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
      score: Number(item.score) || 0,
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

const USAGE_KEY = 'lite_usage_stats_v1'

function recordTodayUsage(verdictKey) {
  try {
    const today = new Date()
    const todayStr = `${today.getFullYear()}-${String(today.getMonth()+1).padStart(2,'0')}-${String(today.getDate()).padStart(2,'0')}`
    const stats = wx.getStorageSync(USAGE_KEY) || {}
    if (stats.lastDate === todayStr) return
    stats.lastDate = todayStr
    stats.days = (stats.days || 0) + 1
    if (!stats.firstDate) stats.firstDate = todayStr
    if (verdictKey === 'long') stats.long = (stats.long || 0) + 1
    else if (verdictKey === 'empty') stats.empty = (stats.empty || 0) + 1
    else stats.mid = (stats.mid || 0) + 1
    wx.setStorageSync(USAGE_KEY, stats)
  } catch (e) {}
}

function loadUsageStats() {
  try {
    return wx.getStorageSync(USAGE_KEY) || { firstDate: '', days: 0, long: 0, mid: 0, empty: 0 }
  } catch (e) { return { firstDate: '', days: 0, long: 0, mid: 0, empty: 0 } }
}

module.exports = {
  LONG,
  MID,
  EMPTY,
  MAP,
  DAILY_QUOTES,
  getDailyQuote,
  calcStreak,
  recordTodayUsage,
  loadUsageStats,
  USAGE_KEY,
  calcVerdict,
  calcHistoryVerdict,
  mapToday,
  mapHistoryList,
  subscribePreviewText,
  formatHeaderDate,
  formatUpdateBadge,
  formatShortDate,
}
