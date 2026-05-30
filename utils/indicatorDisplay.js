/** 指标展示增强：对比昨日/前日、涨跌箭头、板块更新时间 */

const INVERSE_KEYS = new Set(['limitDown', 'break', 'breakLive', 'declineLive', 'limitDownLive'])

function displayText(v, fallback = '--') {
  if (v == null) return fallback
  const s = String(v).trim()
  if (!s || s === '-' || s.toLowerCase() === 'nan' || s.toLowerCase() === 'none' || s.toLowerCase() === 'null') {
    return fallback
  }
  return s
}

function enrichTrend(item) {
  const trend = item.trend || 'flat'
  if (trend === 'flat') {
    return { trendArrow: '', trendGood: null }
  }
  const trendGood = trend === 'up'
  return {
    trendArrow: trend === 'up' ? '↑' : '↓',
    trendGood
  }
}

function parseFirstNumber(v) {
  const s = displayText(v, '')
  const m = s.match(/[+-]?\d+(?:\.\d+)?/)
  return m ? Number(m[0]) : null
}

function parseSignedPercent(v) {
  const s = displayText(v, '')
  const m = s.match(/[+-]\d+(?:\.\d+)?\s*%/)
  return m ? Number(m[0].replace('%', '')) : null
}

function inferValueGood(item) {
  const key = item.key || ''
  const value = displayText(item.displayValue || item.value, '')
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

function enrichAdvance(item) {
  if (item.key !== 'advance' && item.key !== 'advanceLive') return item
  const up = item.advanceUp != null ? item.advanceUp : parseAdvanceUp(item.value)
  let prevUp = item.prevAdvanceUp != null ? item.prevAdvanceUp : parseAdvanceUp(item.yesterday || item.prev)
  if (prevUp === '0' || prevUp === 0) prevUp = '--'
  return {
    ...item,
    label: '上涨家数',
    value: String(up),
    prev: prevUp !== '--' ? String(prevUp) : '--',
    yesterday: prevUp !== '--' ? String(prevUp) : '--'
  }
}

function parseAdvanceUp(str) {
  if (str == null || str === '--') return '--'
  const s = String(str)
  const m = s.match(/涨(\d+)/)
  if (m) return m[1]
  const slash = s.match(/^(\d+)\/\d+/)
  if (slash) return slash[1]
  const n = Number(s)
  return Number.isNaN(n) ? '--' : String(n)
}

function parseDeclineDown(str) {
  if (str == null || str === '--') return '--'
  const s = String(str)
  const m = s.match(/跌(\d+)/)
  if (m) return m[1]
  const slash = s.match(/^\d+\/(\d+)/)
  if (slash) return slash[1]
  return '--'
}

function enrichPeripheral(item) {
  const chgText = displayText(item.chgText || item.chg, '--')
  const price = displayText(item.price != null ? item.price : item.value, '--')
  const hasChg = chgText !== '--' && chgText.includes('%')
  return {
    ...item,
    price,
    value: price,
    chgText: hasChg ? chgText : '--',
    displayValue: price
  }
}

function enrichCell(item) {
  if (!item) return item
  let cell = { ...item }
  cell.prev = cell.prev != null ? cell.prev : (cell.yesterday != null ? String(cell.yesterday) : '')
  cell = enrichAdvance(cell)
  Object.assign(cell, enrichTrend(cell))
  cell.displayValue = cell.value
  const valueGood = cell.trendGood != null ? cell.trendGood : inferValueGood(cell)
  cell.trendGood = cell.trendGood != null ? cell.trendGood : valueGood
  cell.valueClass = valueGood === true ? 'value-hot' : (valueGood === false ? 'value-cold' : '')
  return cell
}

function enrichIndicatorSections(sections) {
  return (sections || []).map(sec => {
    const items = (sec.items || []).map(it => {
      const base = sec.id === 'peripheral' ? enrichPeripheral(it) : enrichCell(it)
      return base
    })
    const rows = sec.layout === 'row3'
      ? [items]
      : chunkRows(items, sec.cols || 3)
    return { ...sec, items, rows }
  })
}

function chunkRows(list, cols) {
  const rows = []
  for (let i = 0; i < list.length; i += cols) {
    rows.push(list.slice(i, i + cols))
  }
  return rows
}

function pickLatestGeneratedAt(data, sections) {
  if (data && data.generatedAtLabel && String(data.generatedAtLabel).includes('更新')) {
    return data.generatedAtLabel
  }
  if (data && data.generatedAt && String(data.generatedAt).includes('更新')) {
    return data.generatedAt
  }
  const { formatGaugeUpdatedAt } = require('./dateDisplay')
  const fromData = formatGaugeUpdatedAt(data)
  if (fromData && fromData !== '更新中') return fromData
  const metas = (sections || []).map(s => s.meta).filter(Boolean)
  const yesterdayMeta = (sections || []).find(s => s.id === 'yesterday')
  if (yesterdayMeta && yesterdayMeta.meta) return yesterdayMeta.meta
  if (metas.length) return metas[0]
  return '更新中'
}

module.exports = {
  enrichIndicatorSections,
  pickLatestGeneratedAt,
  enrichCell,
  displayText,
  INVERSE_KEYS
}
