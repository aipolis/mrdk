/**

 * 三大类指标（共18项）

 */

const { normalizeGrid9, chunkToRows } = require('./grid9')

const { displayText } = require('./indicatorDisplay')

const { enrichIndicatorSections } = require('./indicatorDisplay')



const SECTION_DEFS = [

  { id: 'yesterday', title: '昨日情绪概览', meta: '15:00 更新', layout: 'grid3', cols: 3 },

  { id: 'peripheral', title: '外围情绪及指数', meta: '15:00 更新', layout: 'row3', cols: 3 },

  { id: 'auction', title: '今日竞价情绪', meta: '09:15 更新', layout: 'grid3', cols: 3 },

  { id: 'intraday', title: '盘中实时情绪', meta: '盘中更新', layout: 'grid3', cols: 3 }

]



const AUCTION_DEFS = [

  { key: 'auctionOneWord', label: '竞价一字板' },

  { key: 'auctionVolume', label: '竞价量能' },

  { key: 'yesterdayFirst', label: '昨日首板竞价涨幅' },

  { key: 'yesterdayMulti', label: '昨日连板竞价涨幅' },

  { key: 'recentMulti', label: '最近多板竞价涨幅' },

  { key: 'top10AuctionChg', label: '昨日成交额前10平均竞价涨幅' }

]

const INTRADAY_DEFS = [
  { key: 'sseIndex', label: '昨日涨停指数' },
  { key: 'upRatio', label: '上涨占比' },
  { key: 'limitUpLive', label: '实时涨停' },
  { key: 'limitDownLive', label: '实时跌停' },
  { key: 'marketVolumeLive', label: '全市量能' },
  { key: 'top10AvgChgLive', label: 'T-1成交额前10平均涨幅' },
  { key: 'promoteLive', label: '晋级率' },
  { key: 'breakLive', label: '实时炸板率' }
]



function mapItem(item) {

  if (!item) return null

  const key = item.key || item.name
  let prev = item.prev != null ? String(item.prev)
    : (item.yesterday != null ? String(item.yesterday).replace(/^前日\s*/, '').replace(/^昨\s*/, '') : '')
  if (key === 'advance' && (prev === '0' || prev === '-')) prev = '--'
  if (key === 'oneWord' && prev === '-') prev = '--'

  return {

    key: item.key || item.name,

    label: item.label || item.name || item.title || '',

    value: displayText(item.value),

    prev: displayText(prev),

    yesterday: displayText(prev),

    trend: item.trend || 'flat',

    up: item.up,

    price: item.price != null ? displayText(item.price) : undefined,

    chg: item.chg,

    chgText: item.chgText != null ? displayText(item.chgText) : undefined,

    advanceUp: item.advance_up != null ? item.advance_up : item.advanceUp,

    declineDown: item.decline_down != null ? item.decline_down : item.declineDown,

    prevAdvanceUp: item.prev_advance_up != null ? item.prev_advance_up : item.prevAdvanceUp,

    prevDeclineDown: item.prev_decline_down != null ? item.prev_decline_down : item.prevDeclineDown

  }

}



function normalizePeripheral(data) {

  if (Array.isArray(data.peripheral) && data.peripheral.length) {

    return data.peripheral.map(mapItem).filter(Boolean)

  }

  const overview = data.overview || []

  if (overview.length) {

    return overview.map(o => mapItem({

      key: o.name,

      label: o.name,

      price: o.price || o.value,

      chgText: o.chgText || o.value,

      up: o.up,

      trend: o.up ? 'up' : 'down'

    })).filter(Boolean)

  }

  return [

    { key: 'ftseA50', label: '富时A50指数', price: '--', chgText: '--', trend: 'flat', up: false },

    { key: 'sp500', label: '标普500', price: '--', chgText: '--', trend: 'flat', up: false },

    { key: 'cnh', label: '离岸人民币', price: '--', chgText: '--', trend: 'flat', up: true }

  ]

}



function sanitizeAuctionList(items) {
  if (!Array.isArray(items) || !items.length) return items
  const volItem = items.find(i => i.key === 'auctionVolume')
  const volMissing = displayText(volItem && (volItem.value || volItem.displayValue)) === '--'
  const zeroPct = new Set(['+0.00%', '-0.00%', '0.00%', '0%', '0', '0.0'])
  return items.map(item => {
    const out = { ...item }
    let val = displayText(out.value)
    if (out.key === 'auctionOneWord' && volMissing && (val === '0' || val === '0.0')) val = '--'
    let prev = displayText(out.prev != null ? out.prev : out.yesterday)
    out.value = val
    out.displayValue = val
    out.prev = prev
    out.yesterday = prev
    if (val === '--') {
      out.trend = 'flat'
      delete out.up
    }
    return out
  })
}

const ZERO_PCT = new Set(['+0.00%', '-0.00%', '0.00%', '0%', '0', '0.0'])

function shouldShowAuctionTodayValues() {
  return true
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
  const val = String(item.displayValue != null ? item.displayValue : (item.value != null ? item.value : '')).trim()
  if (!val || val === '--' || ZERO_PCT.has(val)) return null
  return val
}

function archiveByKey(list) {
  const map = {}
  ;(list || []).forEach(it => {
    if (it && it.key) map[it.key] = it
  })
  return map
}

function ingestAuctionPrev(map, items) {
  ;(items || []).forEach(it => {
    if (!it || !it.key) return
    const p = it.prev != null ? it.prev : it.yesterday
    if (p != null && String(p).trim() && String(p).trim() !== '--') {
      map[it.key] = String(p).replace(/^昨\s*/, '').replace(/^前日\s*/, '')
    }
  })
}

function buildAuctionPrevMap(data) {
  const map = {}
  ingestAuctionPrev(map, data && data.auction)
  const sec = ((data && data.indicatorSections) || []).find(s => s && s.id === 'auction')
  ingestAuctionPrev(map, sec && sec.items)

  const refMap = archiveByKey(data && data.refAuctionArchive)
  const prevMap = archiveByKey(data && data.prevAuctionArchive)
  const m = (data && data.metrics) || {}

  AUCTION_DEFS.forEach(({ key }) => {
    if (map[key] && map[key] !== '--') return
    const picked = pickPrevMany(
      prevMap[key] && prevMap[key].prev,
      prevMap[key] && prevMap[key].yesterday,
      auctionArchiveVal(prevMap[key]),
      refMap[key] && refMap[key].prev,
      refMap[key] && refMap[key].yesterday,
      auctionArchiveVal(refMap[key]),
      key === 'auctionOneWord' ? m.auction_one_word_count : null,
      key === 'auctionOneWord' ? m.auction_one_word : null,
      key === 'auctionVolume' ? (m.auction_volume_yi != null ? `${Math.round(Number(m.auction_volume_yi))}亿` : null) : null,
      key === 'yesterdayFirst' && m.first_board_auction_chg != null ? formatPct(m.first_board_auction_chg) : null,
      key === 'yesterdayMulti' && m.multi_board_auction_chg != null ? formatPct(m.multi_board_auction_chg) : null,
      key === 'recentMulti' && m.max_board_auction_chg != null ? formatPct(m.max_board_auction_chg) : null,
      key === 'top10AuctionChg' && m.auction_median != null ? formatPct(m.auction_median) : null,
      key === 'top10AuctionChg' && m.top10_avg_chg != null ? formatPct(m.top10_avg_chg) : null
    )
    if (picked !== '--') map[key] = picked
  })
  return map
}

function mergeAuctionItems(rawItems, data) {
  const prevMap = buildAuctionPrevMap(data)
  const hasServerValue = (list) => (list || []).some(it => {
    const v = displayText(it && (it.displayValue != null ? it.displayValue : it.value))
    return v !== '--' && !ZERO_PCT.has(v)
  })
  const showToday = shouldShowAuctionTodayValues()
    || data.isReportReady !== false
    || hasServerValue(data && data.auction)
    || hasServerValue(rawItems)
  const byKey = {}
  ;((data && data.auction) || []).forEach(it => { if (it && it.key) byKey[it.key] = it })
  ;(rawItems || []).forEach(it => { if (it && it.key) byKey[it.key] = it })

  return AUCTION_DEFS.map(({ key, label }) => {
    const it = byKey[key]
    const prev = pickPrev(showToday && it ? (it.prev != null ? it.prev : it.yesterday) : null, prevMap[key])
    let value = '--'
    if (showToday && it) {
      value = it.displayValue != null ? it.displayValue : it.value
      value = value != null && String(value).trim() !== '' ? String(value) : '--'
      if (key === 'auctionOneWord' && value === '0') value = '--'
    }
    return mapItem({
      key,
      label: (it && it.label) || label,
      value,
      prev,
      yesterday: prev,
      trend: (it && it.trend) || 'flat',
      up: it && it.up
    })
  }).filter(Boolean)
}

function ensureAuctionSection(sections, data) {
  const list = Array.isArray(sections) ? sections.slice() : []
  const idx = list.findIndex(s => s && s.id === 'auction')
  const rawItems = idx >= 0 ? list[idx].items : []
  const items = sanitizeAuctionList(mergeAuctionItems(rawItems, data))
  const def = SECTION_DEFS.find(d => d.id === 'auction') || {}
  const patch = {
    id: 'auction',
    title: (idx >= 0 && list[idx].title) || def.title || '今日竞价情绪',
    meta: (idx >= 0 && list[idx].meta) || def.meta || '',
    layout: (idx >= 0 && list[idx].layout) || def.layout || 'grid3',
    cols: (idx >= 0 && list[idx].cols) || def.cols || 3,
    items,
    pending: items.every(it => it.value === '--')
  }
  if (idx >= 0) list[idx] = { ...list[idx], ...patch }
  else list.push(patch)
  return list
}



function normalizeAuction(data) {

  if (Array.isArray(data.auction) && data.auction.length) {

    return sanitizeAuctionList(data.auction.map(it => mapItem(it)).filter(Boolean))

  }

  const m = data.metrics || {}

  const indMap = {}

  ;(data.indicators || []).forEach(i => { indMap[i.key] = i })



  const auctionUp = indMap.auctionUp && indMap.auctionUp.value



  return AUCTION_DEFS.map(({ key, label }) => {

    if (key === 'auctionOneWord') {

      const v = m.auction_one_word != null ? m.auction_one_word : m.auction_one_word_count

      if (v == null) return { key, label, value: '--', trend: 'flat' }

      return { key, label, value: String(v), trend: 'flat' }

    }

    if (key === 'yesterdayFirst') {
      const v = m.first_board_auction_chg
      if (v == null) return { key, label, value: '--', trend: 'flat' }
      const pct = `${Number(v) >= 0 ? '+' : ''}${Number(v).toFixed(2)}%`
      return { key, label, value: pct, trend: Number(v) >= 0 ? 'up' : 'down', up: Number(v) >= 0 }
    }

    if (key === 'yesterdayMulti') {
      const v = m.multi_board_auction_chg
      if (v == null) return { key, label, value: '--', trend: 'flat' }
      const pct = `${Number(v) >= 0 ? '+' : ''}${Number(v).toFixed(2)}%`
      return { key, label, value: pct, trend: Number(v) >= 0 ? 'up' : 'down', up: Number(v) >= 0 }
    }

    if (key === 'auctionVolume') {
      const v = m.auction_volume_yi
      if (v == null) return { key, label, value: '--', trend: 'flat' }
      return { key, label, value: `${Math.round(Number(v))}亿`, trend: 'flat' }
    }

    if (key === 'recentMulti') {
      const v = m.max_board_auction_chg
      if (v == null) return { key, label, value: '--', trend: 'flat' }
      const pct = `${Number(v) >= 0 ? '+' : ''}${Number(v).toFixed(2)}%`
      return { key, label, value: pct, trend: Number(v) >= 0 ? 'up' : 'down', up: Number(v) >= 0 }
    }

    if (key === 'top10AuctionChg') {

      const med = m.auction_median

      if (med == null || Number(med) === 0) return { key, label, value: '--', trend: 'flat' }

      const v = `${Number(med) >= 0 ? '+' : ''}${Number(med).toFixed(2)}%`

      return { key, label, value: v, trend: Number(med) >= 0 ? 'up' : 'down', up: Number(med) >= 0 }

    }

    return { key, label, value: '--', trend: 'flat' }

  })

}



function resolveSsePrev(data, byKey) {
  const pm = (data && data.prevMetrics) || {}
  if (pm.index_chg != null && !Number.isNaN(Number(pm.index_chg))) {
    return formatPct(pm.index_chg)
  }
  const m = (data && data.metrics) || {}
  if (m.index_chg != null && !Number.isNaN(Number(m.index_chg))) {
    return formatPct(m.index_chg)
  }
  if (byKey.indexChg && byKey.indexChg.value) return String(byKey.indexChg.value)
  return '--'
}

function pickPrev(primary, fallback) {
  const p = primary != null ? String(primary).trim() : ''
  if (p && p !== '--') return p
  const f = fallback != null ? String(fallback).trim() : ''
  return f && f !== '--' ? f : (p || '--')
}

function resolveTop10Prev(data) {
  const m = (data && data.metrics) || {}
  if (m.top10_avg_chg != null && !Number.isNaN(Number(m.top10_avg_chg))) {
    return formatPct(m.top10_avg_chg)
  }
  const fromIntraday = (data && data.intraday || []).find(i => i.key === 'top10AvgChgLive')
  if (fromIntraday) {
    const p = fromIntraday.prev != null ? fromIntraday.prev : fromIntraday.yesterday
    if (p != null && String(p).trim() && String(p).trim() !== '--') return String(p)
  }
  return '--'
}

function resolveVolPrev(data) {
  const fromIntraday = (data && data.intraday || []).find(i => i.key === 'marketVolumeLive')
  if (fromIntraday) {
    const p = fromIntraday.prev != null ? fromIntraday.prev : fromIntraday.yesterday
    if (p != null && String(p).trim() && String(p).trim() !== '--') {
      return String(p).replace(/\s*[+-]?\d+\.?\d*%.*/, '').trim() || String(p)
    }
  }
  const m = (data && data.metrics) || {}
  if (m.volume_raw != null && Number(m.volume_raw) > 0) {
    return `${Math.round(Number(m.volume_raw))}亿`
  }
  const grid = normalizeGrid9(data || {})
  const volCell = grid.find(c => c.key === 'volume')
  if (volCell && volCell.value) {
    const yi = parseVolumeYi(volCell.value)
    if (yi != null && Number(yi) > 0) return `${Math.round(Number(yi))}亿`
  }
  return '--'
}

function dateKey(raw) {
  return String(raw || '').replace(/\D/g, '').slice(0, 8)
}

function getIntradayCompareMetrics(data) {
  const ref = dateKey(data && data.refDate)
  const advice = dateKey(data && (data.adviceDate || data.date))
  const prev = data && data.prevMetrics
  if (ref && advice && ref === advice && prev && Object.keys(prev).length) return prev
  return (data && data.metrics) || {}
}

function buildIntradayPrevMap(data) {
  const grid = normalizeGrid9(data || {})
  const byKey = {}
  grid.forEach(c => { byKey[c.key || c.name] = c })
  const m = getIntradayCompareMetrics(data)
  const prevAdv = m.advance_count != null ? m.advance_count : parseAdvanceFromCell(byKey.advance)
  const prevDec = m.decline_count
  const prevLu = m.limit_up_count != null ? m.limit_up_count : (byKey.limitUp && byKey.limitUp.value)
  const prevLd = m.limit_down_count != null ? m.limit_down_count : (byKey.limitDown && byKey.limitDown.value)
  let prevRatio = '--'
  if (prevAdv != null && prevDec != null) {
    const advN = Number(prevAdv)
    const decN = Number(prevDec)
    const total = advN + decN
    if (advN > 0 && decN > 0 && total >= 500) prevRatio = `${(advN / total * 100).toFixed(1)}%`
  }
  return {
    sseIndex: resolveSsePrev(data, byKey),
    upRatio: prevRatio,
    limitUpLive: prevLu != null ? String(prevLu).replace(/[^\d]/g, '') || String(prevLu) : '--',
    limitDownLive: prevLd != null ? String(prevLd).replace(/[^\d]/g, '') || String(prevLd) : '--',
    marketVolumeLive: resolveVolPrev(data),
    top10AvgChgLive: resolveTop10Prev(data),
    promoteLive: m.promote_rate != null ? formatRate(m.promote_rate) : '--',
    breakLive: m.break_rate != null ? formatRate(m.break_rate) : '--'
  }
}

function enrichIntradayPrev(items, data) {
  const prevMap = buildIntradayPrevMap(data)
  return (items || []).map(it => {
    const fallback = prevMap[it.key]
    const prev = pickPrev(it.prev || it.yesterday, fallback)
    if (it.key === 'upRatio' && Number(((data && data.metrics) || {}).decline_count || 0) <= 0) {
      return { ...it, value: '--', prev, yesterday: prev }
    }
    return { ...it, prev, yesterday: prev }
  })
}

function buildIntradayPlaceholder(data) {
  const prevMap = buildIntradayPrevMap(data)
  return INTRADAY_DEFS.map(({ key, label }) => mapItem({
    key,
    label,
    value: '--',
    prev: prevMap[key] || '--',
    trend: 'flat'
  })).filter(Boolean)
}

function parseVolumeYi(str) {
  if (str == null || str === '--') return null
  const m = String(str).match(/([\d.]+)\s*亿/)
  return m ? m[1] : null
}

function formatPct(n) {
  const v = Number(n)
  if (Number.isNaN(v)) return '--'
  return `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`
}

function formatRate(n) {
  const v = Number(n)
  if (Number.isNaN(v)) return '--'
  return `${Math.round(v)}%`
}

function parseAdvanceFromCell(cell) {
  if (!cell) return null
  if (cell.advance_up != null) return cell.advance_up
  const m = String(cell.value || '').match(/(\d+)/)
  return m ? m[1] : null
}

function resolveIntradayMeta(data) {
  if (data && data.generatedAtLabel && String(data.generatedAtLabel).includes('盘中')) {
    return data.generatedAtLabel.replace(/^盘中\s*/, '今日 ')
  }
  const now = new Date()
  const hm = now.getHours() * 60 + now.getMinutes()
  const wd = now.getDay()
  if (wd === 0 || wd === 6) return '休市'
  if (hm < 9 * 60 + 30) return '今日 9:30 起更新'
  if (hm > 15 * 60) return '今日 15:00 已收盘'
  return '盘中更新'
}

function isIntradayPinnedWindow(date = new Date()) {
  const wd = date.getDay()
  if (wd === 0 || wd === 6) return false
  const hm = date.getHours() * 60 + date.getMinutes()
  return hm >= 9 * 60 && hm <= 15 * 60 + 30
}

const TRADING_SECTION_ORDER = [
  'intraday',
  'longkongRisk',
  'auction',
  'yesterday',
  'peripheral',
]

function orderIndicatorSections(sections) {
  if (!Array.isArray(sections) || !sections.length) return sections || []
  if (isIntradayPinnedWindow()) {
    const byId = {}
    sections.forEach(sec => {
      if (sec && sec.id) byId[sec.id] = sec
    })
    const ordered = TRADING_SECTION_ORDER
      .filter(id => byId[id])
      .map(id => byId[id])
    const known = new Set(TRADING_SECTION_ORDER)
    sections.forEach(sec => {
      if (sec && sec.id && !known.has(sec.id)) ordered.push(sec)
    })
    return ordered.length ? ordered : sections
  }
  let intraday = null
  const rest = []
  sections.forEach(sec => {
    if (sec && sec.id === 'intraday') intraday = sec
    else rest.push(sec)
  })
  if (!intraday) return sections
  return [...rest, intraday]
}

function normalizeIntradayItems(items, data) {
  const placeholder = buildIntradayPlaceholder(data || {})
  const byKey = {}
  placeholder.forEach(it => { byKey[it.key] = it })
  ;(data && data.intraday || []).map(mapItem).filter(Boolean).forEach(it => { byKey[it.key] = it })
  ;(items || []).map(mapItem).filter(Boolean).forEach(it => { byKey[it.key] = it })
  const merged = INTRADAY_DEFS.map(({ key, label }) => {
    const it = byKey[key]
    if (it) {
      const ph = placeholder.find(p => p.key === key)
      const prev = pickPrev(it.prev || it.yesterday, ph && (ph.prev || ph.yesterday))
      return { ...it, label: it.label || label, prev, yesterday: prev }
    }
    return mapItem({ key, label, value: '--', prev: '--', trend: 'flat' })
  }).filter(Boolean)
  return enrichIntradayPrev(merged, data)
}

function ensureIntradaySection(sections, data) {
  const list = Array.isArray(sections) ? sections.slice() : []
  const idx = list.findIndex(s => s && s.id === 'intraday')
  const rawItems = idx >= 0 ? list[idx].items : []
  const items = normalizeIntradayItems(rawItems, data)
  if (!items.length) return list
  const def = SECTION_DEFS.find(d => d.id === 'intraday') || {}
  const patch = {
    id: 'intraday',
    title: def.title || '盘中实时情绪',
    meta: (idx >= 0 && list[idx].meta) || resolveIntradayMeta(data),
    layout: (idx >= 0 && list[idx].layout) || def.layout || 'grid3',
    cols: (idx >= 0 && list[idx].cols) || def.cols || 3,
    items,
    pending: items.every(it => it.value === '--')
  }
  if (idx >= 0) {
    list[idx] = { ...list[idx], ...patch }
  } else {
    list.push(patch)
  }
  return list
}



function normalizeIndicatorSections(data) {

  if (!data) return []



  let sections

  if (Array.isArray(data.indicatorSections) && data.indicatorSections.length) {

    sections = data.indicatorSections.map(sec => {

      const def = SECTION_DEFS.find(d => d.id === sec.id) || {}

      let items = (sec.items || [])
        .filter(item => !['high10', 'high10Live'].includes(item && item.key))
        .map(mapItem)
        .filter(Boolean)
      if (sec.id === 'auction') {
        items = sanitizeAuctionList(mergeAuctionItems(sec.items || [], data))
      }

      return {

        id: sec.id,

        title: sec.title || def.title || '',

        meta: sec.meta || def.meta || '',

        layout: sec.layout || def.layout || 'grid3',

        cols: sec.cols || def.cols || 3,

        pending: sec.pending,

        items

      }

    })

  } else {

    const yesterday = normalizeGrid9(data)
      .filter(item => item && item.key !== 'high10')
      .map(item => ({

      ...mapItem(item),

      label: item.label === 'X板' ? '连板高度' : (item.label === '成交量能' ? '市场量能' : item.label)

      }))

    sections = SECTION_DEFS.map(def => {

      let items = []

      if (def.id === 'yesterday') items = yesterday

      else if (def.id === 'peripheral') items = normalizePeripheral(data)

      else if (def.id === 'auction') items = sanitizeAuctionList(mergeAuctionItems([], data))

      else if (def.id === 'intraday') items = normalizeIntradayItems(data.intraday || [], data)

      return { ...def, items }

    })

  }



  sections = ensureAuctionSection(sections, data)

  sections = ensureIntradaySection(sections, data)

  sections = orderIndicatorSections(sections)

  return enrichIndicatorSections(sections)

}



module.exports = {

  normalizeIndicatorSections,

  normalizeIntradayItems,

  orderIndicatorSections,

  isIntradayPinnedWindow,

  SECTION_DEFS,

  AUCTION_DEFS

}
