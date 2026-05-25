/** 指标板块：items → rows，对比字段标准化 */



const INVERSE_KEYS = new Set(['limitDown', 'break', 'limitDownLive', 'breakLive'])



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

  { key: 'promoteLive', label: 'T-1日涨停晋级率' },

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

function mergeAuctionItems(rawItems, data) {
  const prevMap = buildAuctionPrevMap(data)
  const hasServerValue = (list) => (list || []).some((it) => {
    const v = String(it?.displayValue ?? it?.value ?? '').trim()
    return v && v !== '--' && !ZERO_PCT.has(v)
  })
  const showToday = shouldShowAuctionTodayValues()
    || data?.isReportReady !== false
    || hasServerValue(data?.auction)
    || hasServerValue(rawItems)
  const byKey = {}
  ;(data?.auction || []).forEach((it) => { if (it?.key) byKey[it.key] = it })
  ;(rawItems || []).forEach((it) => { if (it?.key) byKey[it.key] = it })

  return AUCTION_DEFS.map(({ key, label }) => {
    const it = byKey[key]
    const prev = pickPrev(showToday && it ? (it.prev ?? it.yesterday) : null, prevMap[key])
    let value = '--'
    if (showToday && it) {
      value = it.displayValue ?? it.value
      value = value != null && String(value).trim() !== '' ? String(value) : '--'
      if (key === 'auctionOneWord' && value === '0') value = '--'
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



function buildIntradayPrevMap(data) {

  const m = data?.metrics || {}

  const grid = data?.grid9 || []

  const byKey = {}

  grid.forEach((c) => { byKey[c.key || c.name] = c })



  const prevAdv = m.advance_count != null ? m.advance_count : parseAdvanceFromCell(byKey.advance)

  const prevDec = m.decline_count

  const prevLu = m.limit_up_count != null ? m.limit_up_count : byKey.limitUp?.value

  const prevLd = m.limit_down_count != null ? m.limit_down_count : byKey.limitDown?.value



  let prevRatio = '--'

  if (prevAdv != null && prevDec != null) {

    const total = Number(prevAdv) + Number(prevDec)

    if (total >= 50) prevRatio = `${(Number(prevAdv) / total * 100).toFixed(1)}%`

  }



  const idxChg = m.index_chg

  const ssePrev = idxChg != null && !Number.isNaN(Number(idxChg))

    ? `${Number(idxChg) >= 0 ? '+' : ''}${Number(idxChg).toFixed(2)}%`

    : (byKey.index?.value || '--')



  let volPrev = '--'

  if (m.volume_amount && m.volume_amount !== '--') {

    volPrev = String(m.volume_amount)

  } else if (m.volume_raw > 0) {

    volPrev = `${Math.round(Number(m.volume_raw))}亿`

  }



  return {

    sseIndex: ssePrev,

    upRatio: prevRatio,

    limitUpLive: prevLu != null ? String(prevLu).replace(/[^\d]/g, '') || String(prevLu) : '--',

    limitDownLive: prevLd != null ? String(prevLd).replace(/[^\d]/g, '') || String(prevLd) : '--',

    marketVolumeLive: volPrev,

    high10Live: m.high10_count != null ? String(m.high10_count) : '--',

    top10AvgChgLive: m.top10_avg_chg != null ? `${Number(m.top10_avg_chg) >= 0 ? '+' : ''}${Number(m.top10_avg_chg).toFixed(2)}%` : '--',

    promoteLive: m.promote_rate != null ? formatRate(m.promote_rate) : '--',

    breakLive: m.break_rate != null ? formatRate(m.break_rate) : '--',

  }

}



function mergeIntradayItems(rawItems, data) {

  const prevMap = buildIntradayPrevMap(data)

  const byKey = {}

  ;(data?.intraday || []).forEach((it) => { if (it?.key) byKey[it.key] = it })

  ;(rawItems || []).forEach((it) => { if (it?.key) byKey[it.key] = it })



  return INTRADAY_DEFS.map(({ key, label }) => {

    const it = byKey[key]

    if (it) {

      const prev = pickPrev(it.prev ?? it.yesterday, prevMap[key])

      return {

        ...it,

        key,

        label: it.label || label,

        value: it.value != null ? String(it.value) : '--',

        prev,

        yesterday: prev,

      }

    }

    return {

      key,

      label,

      value: '--',

      prev: prevMap[key] || '--',

      yesterday: prevMap[key] || '--',

      trend: 'flat',

    }

  })

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
  if (key === 'oneWord' || key === 'auctionOneWord' || key === 'high10Live') return n > 0
  if (key === 'volume' || key === 'marketVolumeLive' || key === 'auctionVolume') return n > 0
  return null
}



function normalizeCell(item) {

  if (!item) return null

  let prev = item.prev != null ? String(item.prev) : ''

  if (!prev && item.yesterday != null) {

    prev = String(item.yesterday).replace(/^前日\s*/, '').replace(/^昨\s*/, '')

  }

  if (prev === '0' || prev === '-') prev = '--'

  const meta = trendMeta(item)
  const valueGood = item.trendGood != null ? item.trendGood : (meta.good != null ? meta.good : inferValueGood(item))

  return {

    ...item,

    value: item.value != null ? String(item.value) : '--',

    prev,

    trendGood: valueGood,

    trendArrow: meta.text,

    valueClass: valueGood === true
      ? 'value-hot'
      : (valueGood === false ? 'value-cold' : ''),

  }

}



export function normalizeSections(sections, data = null) {

  let list = sections || []

  if (data) {

    list = ensureAuctionSection(list, data)

    list = ensureIntradaySection(list, data)

  }

  return list.map((sec) => {

    const cols = sec.cols || 3

    const items = (sec.items || []).map(normalizeCell).filter(Boolean)

    const rows = sec.rows?.length

      ? sec.rows.map((row) => row.map(normalizeCell).filter(Boolean))

      : chunkToRows(items, cols)

    return { ...sec, items, rows }

  })

}


