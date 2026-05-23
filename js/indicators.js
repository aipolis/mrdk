/** 指标板块：items → rows，对比字段标准化 */

const INVERSE_KEYS = new Set(['limitDown', 'break', 'limitDownLive', 'breakLive'])

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

function normalizeCell(item) {
  if (!item) return null
  let prev = item.prev != null ? String(item.prev) : ''
  if (!prev && item.yesterday != null) {
    prev = String(item.yesterday).replace(/^前日\s*/, '').replace(/^昨\s*/, '')
  }
  if (prev === '0' || prev === '-') prev = '--'
  const meta = trendMeta(item)
  return {
    ...item,
    value: item.value != null ? String(item.value) : '--',
    prev,
    trendGood: item.trendGood != null ? item.trendGood : meta.good,
    trendArrow: meta.text,
  }
}

export function normalizeSections(sections) {
  return (sections || []).map((sec) => {
    const cols = sec.cols || 3
    const items = (sec.items || []).map(normalizeCell).filter(Boolean)
    const rows = sec.rows && sec.rows.length
      ? sec.rows.map((row) => row.map(normalizeCell).filter(Boolean))
      : chunkToRows(items, cols)
    return { ...sec, items, rows }
  })
}
