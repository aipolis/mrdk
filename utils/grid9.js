/** 九宫格指标：兼容 API 无 grid9 时从 indicators / metrics 组装 */



const GRID9_ORDER = [

  { key: 'height', label: '连板高度' },

  { key: 'limitUp', label: '涨停家数' },

  { key: 'seal', label: '封板率' },

  { key: 'promote', label: '晋级率' },

  { key: 'limitDown', label: '跌停家数' },

  { key: 'break', label: '炸板率' },

  { key: 'oneWord', label: '一字板' },

  { key: 'volume', label: '市场量能' },

  { key: 'advance', label: '上涨家数' }

]



function cleanPrev(raw, key) {
  const s = String(raw || '--')
    .replace(/^前日\s*/, '')
    .replace(/^昨\s*/, '')
    .trim() || '--'
  if (s === '-' || s === '0') {
    if (key === 'advance') return '--'
    if (key === 'oneWord') return '--'
  }
  return s
}



function fromIndicators(indicators) {

  if (!indicators || !indicators.length) return []

  const map = {}

  indicators.forEach(item => {

    map[item.key] = item

  })

  return GRID9_ORDER.map(({ key, label }) => {

    const ind = map[key]

    if (!ind) return null

    return {

      key,

      label,

      value: ind.value != null ? String(ind.value) : '--',

      prev: cleanPrev(ind.yesterday, key),
      yesterday: cleanPrev(ind.yesterday, key),

      trend: ind.trend || 'flat',

      advanceUp: ind.advance_up ?? ind.advanceUp,

      declineDown: ind.decline_down ?? ind.declineDown,

      prevAdvanceUp: ind.prev_advance_up ?? ind.prevAdvanceUp,

      prevDeclineDown: ind.prev_decline_down ?? ind.prevDeclineDown

    }

  }).filter(Boolean)

}



function fromMetrics(metrics, prevMetrics) {

  if (!metrics || metrics.limit_up_count == null) return []

  const prev = prevMetrics || {}



  const vol = metrics.volume_amount != null ? String(metrics.volume_amount) : '--'

  const volPrev = prev.volume_amount != null ? String(prev.volume_amount) : '--'

  const adv = metrics.advance_count != null ? metrics.advance_count : '--'

  const dec = metrics.decline_count != null ? metrics.decline_count : '--'

  const pAdv = prev.advance_count
  const pDec = prev.decline_count != null ? prev.decline_count : 0
  const advPrev = (pAdv != null && (Number(pAdv) + Number(pDec) >= 50))
    ? String(pAdv)
    : (pAdv === 0 || pAdv == null ? '--' : String(pAdv))

  const decPrev = prev.decline_count != null ? prev.decline_count : '--'



  const trend = (cur, p, inverse) => {

    if (p == null || p === '-' || p === '--') return 'flat'

    const c = Number(cur)

    const pv = Number(p)

    if (Number.isNaN(c) || Number.isNaN(pv)) return 'flat'

    if (c > pv) return inverse ? 'down' : 'up'

    if (c < pv) return inverse ? 'up' : 'down'

    return 'flat'

  }



  return [

    { key: 'height', label: '连板高度', value: `${metrics.max_board}板`, prev: prev.max_board != null ? `${prev.max_board}板` : '--', trend: trend(metrics.max_board, prev.max_board) },

    { key: 'limitUp', label: '涨停家数', value: String(metrics.limit_up_count), prev: prev.limit_up_count != null ? String(prev.limit_up_count) : '--', trend: trend(metrics.limit_up_count, prev.limit_up_count) },

    { key: 'seal', label: '封板率', value: `${metrics.seal_rate}%`, prev: prev.seal_rate != null ? `${prev.seal_rate}%` : '--', trend: trend(metrics.seal_rate, prev.seal_rate) },

    { key: 'promote', label: '晋级率', value: `${metrics.promote_rate}%`, prev: prev.promote_rate != null ? `${prev.promote_rate}%` : '--', trend: trend(metrics.promote_rate, prev.promote_rate) },

    { key: 'limitDown', label: '跌停家数', value: String(metrics.limit_down_count), prev: prev.limit_down_count != null ? String(prev.limit_down_count) : '--', trend: trend(metrics.limit_down_count, prev.limit_down_count, true) },

    { key: 'break', label: '炸板率', value: `${metrics.break_rate}%`, prev: prev.break_rate != null ? `${prev.break_rate}%` : '--', trend: trend(metrics.break_rate, prev.break_rate, true) },

    { key: 'oneWord', label: '一字板', value: String(metrics.one_word_count != null ? metrics.one_word_count : '--'), prev: prev.one_word_count != null ? String(prev.one_word_count) : '--', trend: trend(metrics.one_word_count, prev.one_word_count) },

    { key: 'volume', label: '市场量能', value: vol, prev: volPrev, trend: trend(metrics.volume_raw, prev.volume_raw) },

    {
      key: 'advance',
      label: '上涨家数',
      value: String(adv),
      prev: advPrev !== '--' ? String(advPrev) : '--',
      advanceUp: adv,
      prevAdvanceUp: advPrev,
      trend: trend(adv, advPrev)
    }

  ]

}



function mergeToNine(fromInd, fromMet) {

  const map = {}

  fromInd.forEach(i => { map[i.key] = i })

  fromMet.forEach(i => {

    if (!map[i.key] || map[i.key].value === '--') map[i.key] = i

  })

  return GRID9_ORDER.map(({ key, label }) => {

    const item = map[key]

    if (item) return { ...item, label: item.label || label, prev: cleanPrev(item.prev || item.yesterday, key) }

    return { key, label, value: '--', prev: '--', trend: 'flat' }

  })

}



function normalizeGrid9(data) {

  if (!data) return []

  if (Array.isArray(data.grid9) && data.grid9.length > 0) {

    return data.grid9.map(item => ({

      ...item,

      prev: cleanPrev(item.prev || item.yesterday, item.key),
      yesterday: cleanPrev(item.yesterday, item.key),

      trend: item.trend || 'flat',

      advanceUp: item.advance_up ?? item.advanceUp,

      declineDown: item.decline_down ?? item.declineDown,

      prevAdvanceUp: item.prev_advance_up ?? item.prevAdvanceUp,

      prevDeclineDown: item.prev_decline_down ?? item.prevDeclineDown

    }))

  }



  const fromInd = fromIndicators(data.indicators)

  const fromMet = fromMetrics(data.metrics, data.prevMetrics)



  if (fromInd.length || fromMet.length) {

    return mergeToNine(fromInd, fromMet)

  }



  const { homeData } = require('./data')

  return homeData.grid9 || []

}



function chunkToRows(list, cols = 3) {

  const rows = []

  const arr = list || []

  for (let i = 0; i < arr.length; i += cols) {

    rows.push(arr.slice(i, i + cols))

  }

  return rows

}



module.exports = { normalizeGrid9, chunkToRows, GRID9_ORDER }


