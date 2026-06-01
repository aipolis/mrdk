/** 指标板块：items → rows，对比字段标准化 */

import { normalizeGrid9 } from './grid9.js'

const INVERSE_KEYS = new Set([
  'limitDown',
  'break',
  'limitDownLive',
  'breakLive',
  'multiFailRate',
  'limitDownRisk',
  'bigLossCount',
])

const SECTION_DEFS = [
  { id: 'yesterday', title: '昨日情绪概览', meta: '15:00 更新', layout: 'grid3', cols: 3 },
  { id: 'peripheral', title: '外围情绪及指数', meta: '15:00 更新', layout: 'row3', cols: 3 },
  { id: 'auction', title: '今日竞价情绪', meta: '09:15 更新', layout: 'grid3', cols: 3 },
  { id: 'intraday', title: '盘中实时情绪', meta: '盘中更新', layout: 'grid3', cols: 3 },
  { id: 'longkongRisk', title: '龙空龙专属风控', meta: '盘中更新', layout: 'grid3', cols: 3 },
]
function displayText(v, fallback = '--') {
  if (v == null) return fallback
  const s = String(v).trim()
  if (!s || s === '-' || s.toLowerCase() === 'nan' || s.toLowerCase() === 'none' || s.toLowerCase() === 'null') {
    return fallback
  }
  return s
}

const LABEL_OVERRIDES = {
  promote: '晋级率',
  promoteLive: '晋级率',
}



const AUCTION_DEFS = [

  { key: 'auctionOneWord', label: '竞价一字板' },

  { key: 'auctionVolume', label: '竞价量能' },

  { key: 'yesterdayFirst', label: '昨日首板竞价涨幅' },

  { key: 'yesterdayMulti', label: '昨日连板竞价涨幅' },

  { key: 'recentMulti', label: '最近多板竞价涨幅' },

  { key: 'top10AuctionChg', label: '昨日成交额前10平均竞价涨幅' },

]



const INTRADAY_DEFS = [

  { key: 'sseIndex', label: '上证涨跌' },

  { key: 'upRatio', label: '上涨占比' },

  { key: 'limitUpLive', label: '实时涨停' },

  { key: 'limitDownLive', label: '实时跌停' },

  { key: 'marketVolumeLive', label: '全市量能' },

  { key: 'high10Live', label: '10日新高' },

  { key: 'top10AvgChgLive', label: 'T-1成交额前10平均涨幅' },

  { key: 'promoteLive', label: '昨日涨停股今日晋级率' },

  { key: 'breakLive', label: '实时炸板率' },

]



const ZERO_PCT = new Set(['+0.00%', '-0.00%', '0.00%', '0%', '0', '0.0'])

function shouldShowAuctionTodayValues() {
  return true
}



function pickPrev(primary, fallback) {

  const p = primary != null ? String(primary).trim().replace(/^昨\s*/, '').replace(/^前日\s*/, '') : ''

  if (p && p !== '--') return p

  const f = fallback != null ? String(fallback).trim() : ''

  return f && f !== '--' ? f : '--'

}



function formatPct(v) {

  const n = Number(v)

  if (v == null || Number.isNaN(n) || Math.abs(n) < 1e-9) return null

  return `${n >= 0 ? '+' : ''}${n.toFixed(2)}%`

}



function formatYi(v) {

  const n = Number(v)

  if (v == null || Number.isNaN(n) || n <= 0) return null

  return `${Math.round(n)}亿`

}



function formatRate(n) {

  const v = Number(n)

  if (Number.isNaN(v)) return '--'

  return `${Math.round(v)}%`

}



function ingestAuctionPrev(map, items) {

  ;(items || []).forEach((it) => {

    if (!it?.key) return

    const p = it.prev ?? it.yesterday

    if (p != null && String(p).trim() && String(p).trim() !== '--') {

      map[it.key] = String(p).replace(/^昨\s*/, '').replace(/^前日\s*/, '')

    }

  })

}



function pickPrevMany(...candidates) {
  for (const c of candidates) {
    const p = c != null ? String(c).trim().replace(/^昨\s*/, '').replace(/^前日\s*/, '') : ''
    if (p && p !== '--' && !ZERO_PCT.has(p)) return p
  }
  return '--'
}

function auctionArchiveVal(item) {
  if (!item) return null
  const val = String(item.displayValue ?? item.value ?? '').trim()
  if (!val || val === '--' || ZERO_PCT.has(val)) return null
  return val
}

function archiveByKey(list) {
  const map = {}
  ;(list || []).forEach((it) => {
    if (it?.key) map[it.key] = it
  })
  return map
}

function buildAuctionPrevMap(data) {
  const map = {}
  ingestAuctionPrev(map, data?.auction)
  const sec = (data?.indicatorSections || []).find((s) => s?.id === 'auction')
  ingestAuctionPrev(map, sec?.items)

  const refMap = archiveByKey(data?.refAuctionArchive)
  const prevMap = archiveByKey(data?.prevAuctionArchive)
  const m = data?.metrics || {}

  AUCTION_DEFS.forEach(({ key }) => {
    if (map[key] && map[key] !== '--') return
    const picked = pickPrevMany(
      prevMap[key]?.prev,
      prevMap[key]?.yesterday,
      auctionArchiveVal(prevMap[key]),
      refMap[key]?.prev,
      refMap[key]?.yesterday,
      auctionArchiveVal(refMap[key]),
      key === 'auctionOneWord' ? m.auction_one_word_count : null,
      key === 'auctionOneWord' ? m.auction_one_word : null,
      key === 'auctionVolume' ? formatYi(m.auction_volume_yi) : null,
      key === 'yesterdayFirst' ? formatPct(m.first_board_auction_chg) : null,
      key === 'yesterdayMulti' ? formatPct(m.multi_board_auction_chg) : null,
      key === 'recentMulti' ? formatPct(m.max_board_auction_chg) : null,
      key === 'top10AuctionChg' ? formatPct(m.auction_median) : null,
      key === 'top10AuctionChg' ? formatPct(m.top10_avg_chg) : null,
    )
    if (picked !== '--') map[key] = picked
  })
  return map
}

function auctionValueFromMetrics(key, metrics) {
  const m = metrics || {}
  if (key === 'auctionOneWord') {
    const v = m.auction_one_word != null ? m.auction_one_word : m.auction_one_word_count
    return v == null ? '--' : String(v)
  }
  if (key === 'auctionVolume') return formatYi(m.auction_volume_yi) || '--'
  if (key === 'yesterdayFirst') return formatPct(m.first_board_auction_chg) || '--'
  if (key === 'yesterdayMulti') return formatPct(m.multi_board_auction_chg) || '--'
  if (key === 'recentMulti') return formatPct(m.max_board_auction_chg) || '--'
  if (key === 'top10AuctionChg') {
    return formatPct(m.auction_median) || formatPct(m.top10_avg_chg) || '--'
  }
  return '--'
}

function mergeAuctionItems(rawItems, data) {
  const prevMap = buildAuctionPrevMap(data)
  const hasServerValue = (list) => (list || []).some((it) => {
    const v = displayText(it?.displayValue ?? it?.value)
    return v !== '--' && !ZERO_PCT.has(v)
  })
  const showToday = shouldShowAuctionTodayValues()
    || data?.isReportReady !== false
    || hasServerValue(data?.auction)
    || hasServerValue(rawItems)
  const byKey = {}
  ;(data?.auction || []).forEach((it) => { if (it?.key) byKey[it.key] = it })
  ;(rawItems || []).forEach((it) => { if (it?.key) byKey[it.key] = it })
  const metrics = data?.metrics || {}

  return AUCTION_DEFS.map(({ key, label }) => {
    const it = byKey[key]
    const prev = pickPrev(showToday && it ? (it.prev ?? it.yesterday) : null, prevMap[key])
    let value = '--'
    if (showToday && it) {
      value = displayText(it.displayValue ?? it.value)
      if (key === 'auctionOneWord' && value === '0') value = '--'
    }
    if (showToday && (value === '--' || ZERO_PCT.has(value))) {
      const fromMetrics = auctionValueFromMetrics(key, metrics)
      if (fromMetrics !== '--' && !ZERO_PCT.has(fromMetrics)) value = fromMetrics
    }
    return {
      key,
      label: it?.label || label,
      value,
      prev,
      yesterday: prev,
      trend: it?.trend || 'flat',
      up: it?.up,
    }
  })
}

function normalizePeripheral(data) {
  if (Array.isArray(data?.peripheral) && data.peripheral.length) {
    return data.peripheral
  }
  const overview = data?.overview || []
  if (overview.length) {
    return overview.map((o) => ({
      key: o.name || o.key,
      label: o.name || o.label,
      price: o.price || o.value,
      chgText: o.chgText || o.value,
      up: o.up,
      trend: o.up ? 'up' : 'down',
    }))
  }
  return [
    { key: 'ftseA50', label: '富时A50指数', price: '--', chgText: '--', trend: 'flat', up: false },
    { key: 'sp500', label: '标普500', price: '--', chgText: '--', trend: 'flat', up: false },
    { key: 'cnh', label: '离岸人民币', price: '--', chgText: '--', trend: 'flat', up: true },
  ]
}

function buildSectionsFromData(data) {
  const yesterday = normalizeGrid9(data).map((item) => ({
    ...item,
    label: item.label === 'X板' ? '连板高度' : (item.label === '成交量能' ? '市场量能' : item.label),
  }))
  return SECTION_DEFS.map((def) => {
    let items = []
    if (def.id === 'yesterday') items = yesterday
    else if (def.id === 'peripheral') items = normalizePeripheral(data)
    else if (def.id === 'auction') items = mergeAuctionItems([], data)
    else if (def.id === 'intraday') items = mergeIntradayItems(data?.intraday || [], data)
    else if (def.id === 'longkongRisk') items = data?.longkongRisk || []
    return { ...def, items }
  })
}



function ensurePeripheralSection(sections, data) {
  const list = Array.isArray(sections) ? [...sections] : []
  const idx = list.findIndex((s) => s?.id === 'peripheral')
  if (idx < 0) return list
  const existing = list[idx]
  if (existing.items?.length) return list
  const items = normalizePeripheral(data)
  if (!items.length) return list
  list[idx] = { ...existing, items }
  return list
}

function ensureAuctionSection(sections, data) {

  const list = Array.isArray(sections) ? [...sections] : []

  const idx = list.findIndex((s) => s?.id === 'auction')

  const rawItems = idx >= 0 ? list[idx].items : []

  const items = mergeAuctionItems(rawItems, data)

  const patch = {

    id: 'auction',

    title: (idx >= 0 && list[idx].title) || '今日竞价情绪',

    meta: (idx >= 0 && list[idx].meta) || '',

    layout: (idx >= 0 && list[idx].layout) || 'grid3',

    cols: (idx >= 0 && list[idx].cols) || 3,

    items,

    pending: items.every((it) => it.value === '--'),

  }

  if (idx >= 0) {

    list[idx] = { ...list[idx], ...patch }

  } else {

    list.push(patch)

  }

  return list

}



function parseAdvanceFromCell(cell) {

  if (!cell) return null

  const m = String(cell.value || '').match(/(\d+)/)

  return m ? m[1] : null

}



function dateKey(raw) {
  return String(raw || '').replace(/\D/g, '').slice(0, 8)
}

function getIntradayCompareMetrics(data) {
  const ref = dateKey(data?.refDate)
  const advice = dateKey(data?.adviceDate || data?.date)
  const prev = data?.prevMetrics
  if (ref && advice && ref === advice && prev && Object.keys(prev).length) return prev
  return data?.metrics || {}
}

function resolveSsePrev(data) {
  const pm = data?.prevMetrics || {}
  if (pm.index_chg != null && !Number.isNaN(Number(pm.index_chg))) {
    return formatPct(pm.index_chg)
  }
  const m = data?.metrics || {}
  if (m.index_chg != null && !Number.isNaN(Number(m.index_chg))) {
    return formatPct(m.index_chg)
  }
  return '--'
}

function resolveTop10Prev(data) {
  const pm = data?.prevMetrics || {}
  if (pm.top10_avg_chg != null && !Number.isNaN(Number(pm.top10_avg_chg))) {
    return formatPct(pm.top10_avg_chg)
  }
  const fromIntraday = (data?.intraday || []).find((i) => i.key === 'top10AvgChgLive')
  if (fromIntraday) {
    const p = fromIntraday.prev ?? fromIntraday.yesterday
    if (p != null && String(p).trim() && String(p).trim() !== '--') return String(p)
  }
  return '--'
}

function resolveVolPrev(data) {
  const fromIntraday = (data?.intraday || []).find((i) => i.key === 'marketVolumeLive')
  if (fromIntraday) {
    const p = fromIntraday.prev ?? fromIntraday.yesterday
    if (p != null && String(p).trim() && String(p).trim() !== '--') {
      return String(p).replace(/\s*[+-]?\d+\.?\d*%.*/, '').trim() || String(p)
    }
  }
  const m = getIntradayCompareMetrics(data)
  if (m.volume_amount && m.volume_amount !== '--') return String(m.volume_amount)
  if (m.volume_raw > 0) return `${Math.round(Number(m.volume_raw))}亿`
  return '--'
}

function resolveHigh10Prev(data) {
  const m = getIntradayCompareMetrics(data)
  if (m.high10_count != null && !Number.isNaN(Number(m.high10_count))) {
    return String(m.high10_count)
  }
  const fromIntraday = (data?.intraday || []).find((i) => i.key === 'high10Live')
  if (fromIntraday) {
    const p = fromIntraday.prev ?? fromIntraday.yesterday
    if (p != null && String(p).trim() && String(p).trim() !== '--') return String(p).split(/\s+/)[0]
  }
  return '--'
}

function buildIntradayPrevMap(data) {
  const grid = data?.grid9 || []
  const byKey = {}
  grid.forEach((c) => { byKey[c.key || c.name] = c })
  const m = getIntradayCompareMetrics(data)
  const prevAdv = m.advance_count != null ? m.advance_count : parseAdvanceFromCell(byKey.advance)
  const prevDec = m.decline_count
  const prevLu = m.limit_up_count != null ? m.limit_up_count : byKey.limitUp?.value
  const prevLd = m.limit_down_count != null ? m.limit_down_count : byKey.limitDown?.value
  let prevRatio = '--'
  if (prevAdv != null && prevDec != null) {
    const advN = Number(prevAdv)
    const decN = Number(prevDec)
    const total = advN + decN
    if (advN > 0 && decN > 0 && total >= 500) prevRatio = `${(advN / total * 100).toFixed(1)}%`
  }
  return {
    sseIndex: resolveSsePrev(data),
    upRatio: prevRatio,
    limitUpLive: prevLu != null ? String(prevLu).replace(/[^\d]/g, '') || String(prevLu) : '--',
    limitDownLive: prevLd != null ? String(prevLd).replace(/[^\d]/g, '') || String(prevLd) : '--',
    marketVolumeLive: resolveVolPrev(data),
    high10Live: resolveHigh10Prev(data),
    top10AvgChgLive: resolveTop10Prev(data),
    promoteLive: m.promote_rate != null ? formatRate(m.promote_rate) : '--',
    breakLive: m.break_rate != null ? formatRate(m.break_rate) : '--',
  }
}

function enrichIntradayPrev(items, data) {
  const prevMap = buildIntradayPrevMap(data)
  return (items || []).map((it) => {
    const fallback = prevMap[it.key]
    const prev = pickPrev(it.prev ?? it.yesterday, fallback)
    if (it.key === 'upRatio' && Number((data?.metrics || {}).decline_count || 0) <= 0) {
      return { ...it, value: '--', prev, yesterday: prev }
    }
    return { ...it, prev, yesterday: prev }
  })
}

function buildIntradayPlaceholder(data) {
  const prevMap = buildIntradayPrevMap(data)
  return INTRADAY_DEFS.map(({ key, label }) => ({
    key,
    label,
    value: '--',
    prev: prevMap[key] || '--',
    yesterday: prevMap[key] || '--',
    trend: 'flat',
  }))
}

function mergeIntradayItems(rawItems, data) {
  const placeholder = buildIntradayPlaceholder(data)
  const byKey = {}
  placeholder.forEach((it) => { byKey[it.key] = it })
  ;(data?.intraday || []).forEach((it) => { if (it?.key) byKey[it.key] = it })
  ;(rawItems || []).forEach((it) => { if (it?.key) byKey[it.key] = it })
  const merged = INTRADAY_DEFS.map(({ key, label }) => {
    const it = byKey[key]
    if (it) {
      const ph = placeholder.find((p) => p.key === key)
      let value = displayText(it.displayValue ?? it.value)
      const m = data?.metrics || {}
      if (key === 'upRatio' && Number(m.decline_count || 0) <= 0) value = '--'
      if (key === 'top10AvgChgLive' && value === '--' && m.top10_avg_chg != null) {
        value = formatPct(m.top10_avg_chg) || '--'
      }
      const prev = pickPrev(it.prev ?? it.yesterday, ph?.prev ?? ph?.yesterday)
      return { ...it, key, label: it.label || label, value, prev, yesterday: prev }
    }
    return {
      key,
      label,
      value: '--',
      prev: placeholder.find((p) => p.key === key)?.prev || '--',
      yesterday: placeholder.find((p) => p.key === key)?.prev || '--',
      trend: 'flat',
    }
  })
  return enrichIntradayPrev(merged, data)
}



function resolveIntradayMeta(data) {

  if (data?.generatedAtLabel && String(data.generatedAtLabel).includes('盘中')) {

    return String(data.generatedAtLabel).replace(/^盘中\s*/, '今日 ')

  }

  const now = new Date()

  const hm = now.getHours() * 60 + now.getMinutes()

  const wd = now.getDay()

  if (wd === 0 || wd === 6) return '休市'

  if (hm < 9 * 60 + 30) return '今日 9:30 起更新'

  if (hm > 15 * 60) return '今日 15:00 已收盘'

  return '盘中更新'

}



function ensureIntradaySection(sections, data) {

  const list = Array.isArray(sections) ? [...sections] : []

  const idx = list.findIndex((s) => s?.id === 'intraday')

  const rawItems = idx >= 0 ? list[idx].items : []

  const items = mergeIntradayItems(rawItems, data)

  const patch = {

    id: 'intraday',

    title: '盘中实时情绪',

    meta: (idx >= 0 && list[idx].meta) || resolveIntradayMeta(data),

    layout: (idx >= 0 && list[idx].layout) || 'grid3',

    cols: (idx >= 0 && list[idx].cols) || 3,

    items,

    pending: items.every((it) => it.value === '--'),

  }

  if (idx >= 0) {

    list[idx] = { ...list[idx], ...patch }

  } else {

    list.push(patch)

  }

  return list

}

function resolveLongkongRiskItems(rawItems, data) {
  if (rawItems?.length) return rawItems
  if (data?.longkongRisk?.length) return data.longkongRisk
  const fromSec = (data?.indicatorSections || []).find((s) => s?.id === 'longkongRisk')
  if (fromSec?.items?.length) return fromSec.items
  return []
}

function ensureLongkongRiskSection(sections, data) {
  const list = Array.isArray(sections) ? [...sections] : []
  const idx = list.findIndex((s) => s?.id === 'longkongRisk')
  const rawItems = idx >= 0 ? list[idx].items : []
  const items = resolveLongkongRiskItems(rawItems, data)
  if (!items.length) return list

  const def = SECTION_DEFS.find((d) => d.id === 'longkongRisk') || {}
  const patch = {
    id: 'longkongRisk',
    title: (idx >= 0 && list[idx].title) || def.title || '龙空龙专属风控',
    meta: (idx >= 0 && list[idx].meta) || def.meta || '盘中更新',
    layout: (idx >= 0 && list[idx].layout) || def.layout || 'grid3',
    cols: (idx >= 0 && list[idx].cols) || def.cols || 3,
    items,
    pending: items.every((it) => displayText(it?.displayValue ?? it?.value) === '--'),
  }
  if (idx >= 0) {
    list[idx] = { ...list[idx], ...patch }
    return list
  }
  const intraIdx = list.findIndex((s) => s?.id === 'intraday')
  if (intraIdx >= 0) list.splice(intraIdx, 0, patch)
  else list.push(patch)
  return list
}

export function chunkToRows(list, cols = 3) {

  const rows = []

  const arr = list || []

  for (let i = 0; i < arr.length; i += cols) {

    rows.push(arr.slice(i, i + cols))

  }

  return rows

}



function trendMeta(cell) {

  const t = cell.trend

  if (t !== 'up' && t !== 'down') return { text: '', good: null }

  const inverse = INVERSE_KEYS.has(cell.key)

  const good = inverse ? t === 'down' : t === 'up'

  return { text: t === 'up' ? '↑' : '↓', good }

}

function parseFirstNumber(v) {
  const s = String(v ?? '').trim()
  const m = s.match(/[+-]?\d+(?:\.\d+)?/)
  return m ? Number(m[0]) : null
}

function inferNumericTrend(item, prev) {
  const now = parseFirstNumber(item?.displayValue ?? item?.value)
  const old = parseFirstNumber(prev)
  if (now == null || old == null || Math.abs(now - old) < 1e-9) return null
  return now > old ? 'up' : 'down'
}

function parseSignedPercent(v) {
  const s = String(v ?? '').trim()
  const m = s.match(/[+-]\d+(?:\.\d+)?\s*%/)
  return m ? Number(m[0].replace('%', '')) : null
}

function inferValueGood(item) {
  const key = item.key || ''
  const value = String(item.displayValue || item.value || '').trim()
  if (!value || value === '--') return null

  const signedPct = parseSignedPercent(value)
  if (signedPct != null) {
    if (signedPct === 0) return null
    return INVERSE_KEYS.has(key) ? signedPct < 0 : signedPct > 0
  }

  const n = parseFirstNumber(value)
  if (n == null) return null

  if (key === 'upRatio') return n >= 50
  if (key === 'advance' || key === 'advanceLive') return n >= 2500
  if (key === 'height') return n >= 3
  if (key === 'limitUp' || key === 'limitUpLive') return n >= 50
  if (key === 'limitDown' || key === 'limitDownLive') return n <= 10
  if (key === 'seal') return n >= 60
  if (key === 'promote' || key === 'promoteLive') return n >= 25
  if (key === 'break' || key === 'breakLive') return n <= 30
  if (key === 'highBreakFeedback') return n > 0
  if (key === 'limitUpPremium') return n >= 0
  if (key === 'multiFailRate') return n <= 60
  if (key === 'resealRate') return n >= 70
  if (key === 'limitDownRisk') return n <= 10
  if (key === 'bigLossCount') return n <= 20
  if (key === 'oneWord' || key === 'auctionOneWord' || key === 'high10Live') return n > 0
  if (key === 'volume' || key === 'marketVolumeLive' || key === 'auctionVolume') return n > 0
  return null
}



function enrichAdvance(item) {
  if (item.key !== 'advance' && item.key !== 'advanceLive') return item
  const up = item.advanceUp != null ? item.advanceUp : parseAdvanceFromCell(item)
  let prevUp = item.prevAdvanceUp != null ? item.prevAdvanceUp : parseAdvanceFromCell({ value: item.yesterday || item.prev })
  if (prevUp === '0' || prevUp === 0) prevUp = '--'
  return {
    ...item,
    label: '上涨家数',
    value: String(up),
    prev: prevUp !== '--' ? String(prevUp) : '--',
    yesterday: prevUp !== '--' ? String(prevUp) : '--',
  }
}

function enrichPeripheral(item) {
  let chgText = displayText(item.chgText ?? item.chg, '--')
  if (chgText === '--' && item.chg != null && !Number.isNaN(Number(item.chg))) {
    const n = Number(item.chg)
    chgText = `${n >= 0 ? '+' : ''}${n.toFixed(2)}%`
  }
  const price = displayText(item.price ?? item.value)
  const hasChg = chgText !== '--' && chgText.includes('%')
  return {
    ...item,
    price,
    value: price,
    chgText: hasChg ? chgText : '--',
    displayValue: price,
  }
}

function normalizeCell(item, sectionId) {
  if (!item) return null
  let cell = { ...item }
  if (sectionId === 'peripheral') cell = enrichPeripheral(cell)
  else cell = enrichAdvance(cell)

  let prev = cell.prev != null ? String(cell.prev) : ''
  if (!prev && cell.yesterday != null) {
    prev = String(cell.yesterday).replace(/^前日\s*/, '').replace(/^昨\s*/, '')
  }
  if (prev === '0' || prev === '-') prev = '--'

  const value = displayText(cell.displayValue ?? cell.value)
  const numericTrend = inferNumericTrend({ ...cell, value }, prev)
  const meta = trendMeta({
    ...cell,
    trend: numericTrend || cell.trend,
  })
  const valueGood = cell.trendGood != null ? cell.trendGood : (meta.good != null ? meta.good : inferValueGood({ ...cell, value }))

  return {
    ...cell,
    label: LABEL_OVERRIDES[cell.key] || cell.label,
    value,
    displayValue: value,
    prev,
    trendGood: valueGood,
    trendArrow: meta.text,
    valueClass: valueGood === true ? 'value-hot' : (valueGood === false ? 'value-cold' : ''),
  }
}



function isIntradayPinnedWindow() {
  const now = new Date()
  const wd = now.getDay()
  if (wd === 0 || wd === 6) return false
  const hm = now.getHours() * 60 + now.getMinutes()
  return hm >= 9 * 60 && hm <= 15 * 60 + 30
}

const TRADING_SECTION_ORDER = [
  'intraday',
  'longkongRisk',
  'auction',
  'yesterday',
  'peripheral',
]

function pinLiveSections(sections) {
  const list = Array.isArray(sections) ? [...sections] : []
  if (!list.length) return list
  if (isIntradayPinnedWindow()) {
    const byId = new Map()
    list.forEach((sec) => {
      if (sec?.id) byId.set(sec.id, sec)
    })
    const ordered = TRADING_SECTION_ORDER
      .filter((id) => byId.has(id))
      .map((id) => byId.get(id))
    const known = new Set(TRADING_SECTION_ORDER)
    list.forEach((sec) => {
      if (sec?.id && !known.has(sec.id)) ordered.push(sec)
    })
    return ordered.length ? ordered : list
  }
  const intraday = list.find((s) => s?.id === 'intraday')
  if (!intraday) return list
  const rest = list.filter((s) => s?.id !== 'intraday')
  return [...rest, intraday]
}

export function normalizeSections(sections, data = null) {
  let list = sections || []
  if (data && !list.length) {
    list = buildSectionsFromData(data)
  }
  if (data) {
    list = ensurePeripheralSection(list, data)
    list = ensureAuctionSection(list, data)
    list = ensureLongkongRiskSection(list, data)
    list = ensureIntradaySection(list, data)
  }
  list = pinLiveSections(list)
  return list.map((sec) => {
    const cols = sec.cols || 3
    const sid = sec.id || ''
    const items = (sec.items || []).map((it) => normalizeCell(it, sid)).filter(Boolean)
    const rows = sec.rows?.length
      ? sec.rows.map((row) => row.map((it) => normalizeCell(it, sid)).filter(Boolean))
      : (sec.layout === 'row3' ? [items] : chunkToRows(items, cols))
    return { ...sec, items, rows }
  })
}
